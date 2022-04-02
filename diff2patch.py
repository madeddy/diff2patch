#!/usr/bin/env python3
"""
Diff2patch is a tool which compares two directorys trees, e.g old/new, and
produces another directory, which contains all different or in the second dir
added objects.
"""

import os
import sys
import argparse
from pathlib import Path as pt
import tempfile
import shutil
import filecmp
import logging
import textwrap

tty_colors = True
if sys.platform.startswith('win32'):
    try:
        from colorama import init
        init(autoreset=True)
    except ImportError:
        tty_colors = False


__title__ = 'Diff2patch'
__license__ = 'Apache 2.0'
__author__ = 'madeddy'
__status__ = 'Development'
__version__ = '0.1.0-alpha'


# TODO:
# Add to message system more infos
# Opti file/dir counter @end report
# Use tmp mechanics also for report option (and move in case: console just not
# the content)


class D2p_Common:
    """This provides shared methods and variables for child classes."""
    name = __title__
    verbosity = 1

    count = {'dif_fl_found': 0, 'new_fl_found': 0, 'fun_fl_found': 0, 'fl_total': 0}
    std, ul, red, gre, ora, blu, ylw, bg_blu, bg_red = (
        '\x1b[0m', '\x1b[03m', '\x1b[31m', '\x1b[32m', '\x1b[33m', '\x1b[34m',
        '\x1b[93m', '\x1b[44;30m', '\x1b[45;30m' if tty_colors else '')

    @classmethod
    def telltale(cls, fraction, total, obj):
        """Returns a percentage-meter like output for use in tty."""
        return f"[{cls.bg_blu}{fraction / float(total):05.1%}{cls.std}] {obj!s:>4}"

    @classmethod
    def inf(cls, inf_level, msg, m_sort=None):
        """Outputs by the current verboseness level allowed infos."""
        if cls.verbosity >= inf_level:  # TODO: use self.tty ?
            ind1 = f"{cls.name}:{cls.gre} >> {cls.std}"
            ind2 = " " * 12
            if m_sort == 'warn':
                ind1 = f"{cls.name}:{cls.ylw} WARNING {cls.std}> "
                ind2 = " " * 16
            elif m_sort == 'cau':
                ind1 = f"{cls.name}:{cls.red} CAUTION {cls.std}> "
                ind2 = " " * 20
            elif m_sort == 'raw':
                print(ind1, msg)
                return

            print(textwrap.fill(msg, width=90, initial_indent=ind1,
                  subsequent_indent=ind2))

    @classmethod
    def _void_dir(cls, dst):
        """Checks if given directory has content."""
        return not any(dst.iterdir())

    @classmethod
    def _make_dirstruct(cls, dst):
        """Constructs any needet output directorys if they not already exist."""
        if not dst.exists():
            cls.inf(2, f"Creating directory structure for: {dst}")
            dst.mkdir(parents=True, exist_ok=True)


class DirTreeCmp(D2p_Common, filecmp.dircmp):
    """
    This class compiles a diff object list of two given dirs for comparison.
    A modified version of dircmp is used where shallow can be choosen.
    """
    new_only_all = []
    diff_all = []
    funny_all = []
    survey_lst = []

    def __init__(self, old, new, ignore=None, hide=None, shallow=True):
        self.cmp_inst = None
        super().__init__(old, new, ignore, hide)
        self.left = old
        self.right = new
        self.ignore.extend([
            'Thumbs.db', 'Thumbs.db:encryptable', 'desktop.ini', '.directory',
            '.DS_Store', 'log.txt', 'traceback.txt'])
        self.shallow = shallow
        # "self.right" needs to stay as str because the parent class, so we need
        # another name for the pathlike
        self.new_pt = pt(new)

    def phase3(self):
        self.same_files, self.diff_files, self.funny_files = filecmp.cmpfiles(
            self.left, self.right, self.common_files, self.shallow)

    def phase4(self):
        self.subdirs = {}
        for _cd in self.common_dirs:
            cd_l = os.path.join(self.left, _cd)
            cd_r = os.path.join(self.right, _cd)
            self.subdirs[_cd] = self.__class__(
                cd_l, cd_r, self.ignore, self.hide, self.shallow)

    filecmp.dircmp.methodmap.update(
        same_files=phase3, diff_files=phase3, funny_files=phase3, subdirs=phase4)

    def _process_hits(self, in_lst):
        """Helper to compile the directory object lists."""
        return [self.new_pt.joinpath(entry) for entry in in_lst if in_lst]

    def _gather_inst_hits(self):
        """Adds for every subdir instance the findings."""
        self.new_only_all.extend(self._process_hits(self.right_only))
        self.diff_all.extend(self._process_hits(self.diff_files))
        self.funny_all.extend(self._process_hits(self.funny_files))

    def _recursive_cmp(self):
        """Lets the instance iterate recursively through the dir tree."""
        self._gather_inst_hits()
        for self.cmp_inst in self.subdirs.values():
            self.cmp_inst._recursive_cmp()

    def diff_survey(self):
        """Delivers a complete list of the differences betwen the two trees.
        Entrys are pathlike abolute paths."""
        self.survey_lst = [ele for lst in (
            self.new_only_all, self.diff_all, self.funny_all) for ele in lst]

    def run_compare(self):
        """Controls the compare process and returns the outcome."""
        self._recursive_cmp()
        if self.funny_all:
            # NOTE: perhaps do something with this e.g. deeper checks, warns
            # etc.
            # (Well shit! We have UFO's! <unidentified file objects>)
            pass
        self.diff_survey()

        self.count['dif_fl_found'] += len(self.diff_all)
        self.count['new_fl_found'] += len(self.new_only_all)
        self.count['fun_fl_found'] += len(self.funny_all)
        self.count['fl_total'] += len(self.survey_lst)
        self.inf(2, f"We found {self.count['dif_fl_found']} different"
                 f" files, {self.count['new_fl_found']} additional files"
                 f" in the right dir and {self.count['fun_fl_found']} non"
                 f"comparable files.")

        return self.survey_lst


class D2p(D2p_Common):
    """
    Class which backups a list of given path objects to a target dir. Can be
    done as pure directory tree or as archive of given type."""
    d2p_tmp_dir = None
    outdir = 'diff2patch_out'
    outdir_pt = None

    def __init__(self, survey_lst, new_pt, out_base_pt=None):
        self.survey_lst = survey_lst
        self._inp_pt = new_pt
        self.out_base_pt = new_pt.parent if not out_base_pt else pt(
            out_base_pt).resolve(strict=True)

    def _exit(self):
        self.inf(0, "Exiting Diff2Patch.")
        for i in range(3, -1, -1):
            print(f"{D2p_Common.bg_red}{i}%{D2p_Common.std}", end='\r')
        sys.exit(0)

    def _dispose(self, outp=False):
        """Removes temporary content and the outdir_pt if empty."""
        if self.d2p_tmp_dir:
            shutil.rmtree(self.d2p_tmp_dir)
        if outp:
            shutil.rmtree(self.outdir_pt)

    def _outp_check_user(self):
        self.inf(0, f"The output dir '{self.outdir_pt}' exists already. If we "
                 "proceed the content will be replaced!", m_sort='cau')
        while True:
            userinp = input("Type y/n : ").lower()
            if userinp in 'yes':
                break
            elif userinp in 'no':
                self._exit()
            # TODO With py3.10 widely used we can maybe replace this
            # @pattern matching
            # match userinp:
            #     case 'y' | 'yes':
            #         break
            #     case 'n' | 'no':
            #         self._exit()

        self._dispose(outp=True)

    def _make_output(self):
        """Constructs outdir path and structure."""
        self.outdir_pt = self.out_base_pt / self.outdir
        if self.outdir_pt.exists() and not self._void_dir(self.outdir_pt):
            self._outp_check_user()
        self._make_dirstruct(self.outdir_pt)

    def _pack_difftree(self, fmt):
        """Constructs a archive with the outdir content."""
        if fmt not in ['zip', 'tar']:
            fmt += 'tar'
        out_arch = self.outdir_pt.joinpath('d2p_patch')
        shutil.make_archive(out_arch, fmt, self.d2p_tmp_dir)

    def _mv_tmp2outdir(self):
        """Moves temporary content to real output."""
        # FIXME: move does error if src exists in dst; how?
        for entry in self.d2p_tmp_dir.iterdir():
            shutil.move(entry, self.outdir_pt)

    def _gather_difftree(self):
        """Copys the differing objects to the temp outdir path."""

        for src in self.survey_lst:
            rel_src = src.relative_to(self._inp_pt)
            dst = self.d2p_tmp_dir.joinpath(rel_src)

            if src.is_dir():
                shutil.copytree(src, dst,  # symlinks=False,  # ignore=ignores,
                                dirs_exist_ok=True)
            elif src.is_file():
                self._make_dirstruct(dst.parent)
                shutil.copy2(src, dst)

    def run(self):
        """Controls and executes the collection of files in tmp."""
        self.d2p_tmp_dir = pt(tempfile.mkdtemp(
            prefix='Diff2Patch.', suffix='.tmp'))
        self._make_output()
        self._gather_difftree()

        if self._void_dir(self.d2p_tmp_dir):
            self.inf(2, "No files for a patch collected.")
        else:
            self.inf(2, f"Collected {D2p_Common.count['fl_total']} patch files in "
                     f"{self.outdir_pt!s}")


def _print_to(label, inp_lst, log_handler):
    """'Helper func which prints the report out."""
    logging.basicConfig(format='%(message)s', level=logging.INFO, handlers=log_handler)
    logging.info(f"\n{'-' * 80}\n{'#' * 10} {label} elements ###\n")

    for entry in inp_lst:
        logging.info(f"{label} {str(entry)}")


def _print_diff(inp_lsts, report, outdir_pt):
    """
    This manages the printout of the diff report to the given target.
    Available targets are:
        stdout
        file
        both
    """
    # TODO With py3.10 widely used we could replace this
    # @pattern matching
    # e.g.
    # match report:
    #     case 'console':
    #         log_con = logging.StreamHandler(sys.stdout)
    #     case 'file':
    #         log_fle = logging.FileHandler(out_f, mode='a+')
    #     case 'both':
    #         log_con = logging.StreamHandler(sys.stdout)
    #         log_fle = logging.FileHandler(out_f, mode='a+')

    out_f = outdir_pt.joinpath('d2p_report.txt') if report != 'console' else pt(
        tempfile.gettempdir()).joinpath('d2p.dummy')
    out_f.unlink(missing_ok=True)

    log_fle = logging.FileHandler(out_f, mode='a+')
    log_con = logging.StreamHandler(sys.stdout)
    log_handler = (log_con, )  # logging.NullHandler()
    if report == 'file':
        log_handler = (log_fle, )
    elif report == 'both':
        log_handler = log_con, log_fle

    _print_to("Diff2patch report", '', log_handler)
    _print_to("right only", inp_lsts.new_only_all, log_handler)
    _print_to("diff", inp_lsts.diff_all, log_handler)
    _print_to("funny", inp_lsts.funny_all, log_handler)


def chk_indirs(inp):
    """Helper to check the input directorys for validity."""
    if not pt(inp).resolve(strict=True).is_dir():
        raise NotADirectoryError(
            f"Error: Input needs to be a directory path: {inp}")
    return pt(inp)


def _parse_args():
    """Gets the args if CLI is used."""
    aps = argparse.ArgumentParser()
    aps.add_argument(
        'old',
        action='store',
        type=str,
        help='Old/left directory')
    aps.add_argument(
        'new',
        action='store',
        type=str,
        help='New/right directory')
    opts = aps.add_mutually_exclusive_group(required=True)
    opts.add_argument(
        '-d', '--dir',
        action='store_true',
        help='Outputs the diff to a directory.')
    opts.add_argument(
        '-a', '--archive',
        type=str,
        choices=('xz', 'gz', 'bz2', 'zip', 'tar'),
        help='Outputs the diff as archive of given type.')
    opts.add_argument(
        '-r', '--report',
        type=str,
        choices=('console', 'file', 'both'),
        help='Outputs the diff as comparison report to given target.')
    aps.add_argument(
        '-o', '--outpath',
        action='store',
        type=str,
        help='Output path for the differing files, dirs.'
             ' Defaults to the parent of <new>')
    aps.add_argument(
        '-i', '--indepth',
        action='store_false',
        help='Compares the files content instead just their stats.')
    aps.add_argument(
        '--verbose',
        metavar='level [0-2]',
        type=int,
        choices=range(0, 3),
        help='Amount of info output. 0:none, 2:much, default:1')
    aps.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s : { __title__} {__version__}')
    return aps.parse_args()


def main(cfg):
    """Main block of the module with functionality for use on CLI."""
    if not sys.version_info[:2] >= (3, 9):
        raise Exception("Must be executed in Python 3.9 or later.\n"
                        "You are running {}".format(sys.version))

    old = chk_indirs(cfg.old)
    new = chk_indirs(cfg.new)

    dtc = DirTreeCmp(old, new, shallow=cfg.indepth)
    survey = dtc.run_compare()

    d2p = D2p(survey, new, out_base_pt=cfg.outpath)
    if cfg.report:
        if cfg.report != 'console':
            d2p._make_output()
        _print_diff(dtc, cfg.report, d2p.outdir_pt)
    else:
        d2p.run()
        if cfg.dir:
            d2p._mv_tmp2outdir()
        elif cfg.archive:
            d2p._pack_difftree(cfg.archive)
        d2p._dispose()

    d2p.inf(0, "Choosen task completed.")


if __name__ == "__main__":
    main(_parse_args())
