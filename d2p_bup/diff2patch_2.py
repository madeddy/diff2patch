#!/usr/bin/env python3
"""
Diff2patch is a tool which compares two directorys trees, e.g old/new, and
produces another directory, which contains the different or in the second dir
added objects.
"""


import os
import sys
import argparse
from pathlib import Path as pt
# from types import GenericAlias
import stat
import tempfile
import shutil
# import filecmp
import itertools
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


# TODO: Add message system
# use perhaps tempdir for diff content
# Add file/dir counter and patch size info to end report


__all__ = ['cmp', 'DirTreeCmp', 'cmpfiles', 'DEFAULT_IGNORES']

_cache = {}
BUFSIZE = 8 * 1024

DEFAULT_IGNORES = [
    'RCS', 'CVS', 'tags', '.git', '.hg', '.bzr', '_darcs', '__pycache__']


def cmp(f1, f2, shallow=True):
    """
    Compare two files.
    Arguments:
    f1 -- First file name
    f2 -- Second file name
    shallow -- treat files as identical if their stat signatures (type, size,
               mtime) are identical. Otherwise, files are considered different
               if their sizes or contents differ.  [default: True]
    Return value:
    True if the files are the same, False otherwise.
    This function uses a cache for past comparisons and the results,
    with cache entries invalidated if their stat information
    changes.  The cache may be cleared by calling clear_cache().
    """

    s1 = _sig(f1)
    s2 = _sig(f2)
    if s1[0] != stat.S_IFREG or s2[0] != stat.S_IFREG:
        return False
    if shallow and s1 == s2:
        return True
    if s1[1] != s2[1]:
        return False

    outcome = _cache.get((f1, f2, s1, s2))
    if outcome is None:
        outcome = _do_cmp(f1, f2)
        # limit the maximum size of the cache
        if len(_cache) > 100:
            _cache.clear()
        _cache[f1, f2, s1, s2] = outcome
    return outcome


def _sig(inp_fl):
    fl_st = os.stat(inp_fl)
    return (stat.S_IFMT(fl_st.st_mode), fl_st.st_size, fl_st.st_mtime)


def _do_cmp(f1, f2):
    bufsize = BUFSIZE
    with open(f1, 'rb') as fp1, open(f2, 'rb') as fp2:
        while True:
            b1 = fp1.read(bufsize)
            b2 = fp2.read(bufsize)
            if b1 != b2:
                return False
            if not b1:
                return True


def cmpfiles(a, b, common, shallow=True):
    """
    Compare common files in two directories.
    a, b -- directory names
    common -- list of file names found in both directories
    shallow -- if true, do comparison based solely on stat() information
    Returns a tuple of three lists:
      files that compare equal
      files that are different
      filenames that aren't regular files.
    """
    res = ([], [], [])
    for x in common:
        ax = os.path.join(a, x)
        bx = os.path.join(b, x)
        res[_cmp(ax, bx, shallow)].append(x)
    return res


def _cmp(a, b, sh):
    """
    Compare two files. Returns:
      0 for equal
      1 for different
      2 for funny cases (can't stat, etc.)
    """
    try:
        return not abs(cmp(a, b, sh))
    except OSError:
        return 2


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


class DirTreeCmp(D2p_Common):
    """
    This class compiles a diff object list of two given dirs for comparison.
    It uses also a modified version of dircmp where shallow can be choosen and
    with added corrected subclassing from py3.10.
    """
    diff_all = []
    funny_all = []
    new_only_all = []
    survey_lst = []

    def __init__(self, old, new, ignore=None, hide=None, shallow=True):
        self.old = pt(old).resolve()
        self.new = pt(new).resolve()
        self.hide = [os.curdir, os.pardir] if hide is None else hide
        self.ignore = DEFAULT_IGNORES if ignore is None else ignore

        self.cmp_inst = None
        self.new_pt = pt(self.new)

        # print(f"IGNORE init {self.ignore}")
        self.ignore.extend([
            'Thumbs.db', 'Thumbs.db:encryptable', 'desktop.ini', '.directory',
            '.DS_Store', 'log.txt', 'traceback.txt'])
        self.shallow = shallow

        # self.cmp_inst = None
        # self.diff_all = []
        # self.funny_all = []
        # self.new_only_all = []
        # self.survey_lst = []

    def _filter(self, skip_list, inp_pt):
        """Return a copy with items that occur in skip removed."""
        # return [entry for entry in inp_list if entry not in skip_list]
        return [entry.name for entry in os.scandir(inp_pt) if entry.name not in skip_list]

    def _get_dirlist(self, inp_pt):
        """Returns all directory content."""
        # skip_list = self.hide + self.ignore
        # raw_dirlist = [entry.name for entry in os.scandir(inp_pt)]
        filtered_dirlist = self._filter(self.hide + self.ignore, inp_pt)
        return filtered_dirlist.sort()

    def phase0(self):
        """Compare everything except common subdirectories"""
        self.old_list = self._get_dirlist(self.old)
        self.new_list = self._get_dirlist(self.new)

    def _make_lists(self, inp_a, inp_b):
        """Returns all directory content."""
        return list(map(inp_a.__getitem__, inp_b))

    def phase1(self):
        """Compute common names"""
        a = dict(zip(map(os.path.normcase, self.old_list), self.old_list))
        b = dict(zip(map(os.path.normcase, self.new_list), self.new_list))
        self.common = self._make_lists(a, filter(b.__contains__, a))
        # self.old_only = self._make_lists(a, self._filter(b, a))
        # self.new_only = self._make_lists(b, self._filter(a, b))

        # self.common = list(map(a.__getitem__, filter(b.__contains__, a)))
        self.old_only = list(map(a.__getitem__, itertools.filterfalse(b.__contains__, a)))
        self.new_only = list(map(b.__getitem__, itertools.filterfalse(a.__contains__, b)))

    def phase2(self):  # Distinguish files, directories, funnies
        self.common_dirs = []
        self.common_files = []
        self.common_funny = []

        for x in self.common:
            a_path = os.path.join(self.old, x)
            b_path = os.path.join(self.new, x)

            ok = 1
            try:
                a_stat = os.stat(a_path)
            except OSError:
                # print('Can\'t stat', a_path, ':', why.args[1])
                ok = 0
            try:
                b_stat = os.stat(b_path)
            except OSError:
                # print('Can\'t stat', b_path, ':', why.args[1])
                ok = 0

            if ok:
                a_type = stat.S_IFMT(a_stat.st_mode)
                b_type = stat.S_IFMT(b_stat.st_mode)
                if a_type != b_type:
                    self.common_funny.append(x)
                elif stat.S_ISDIR(a_type):
                    self.common_dirs.append(x)
                elif stat.S_ISREG(a_type):
                    self.common_files.append(x)
                else:
                    self.common_funny.append(x)
            else:
                self.common_funny.append(x)

    # def chk_files(self):
    def phase3(self):
        self.same_files, self.diff_files, self.funny_files = cmpfiles(
            self.old, self.new, self.common_files, self.shallow)

    # def chk_subdirs(self):
    def phase4(self):
        self.subdirs = {}
        for _cd in self.common_dirs:
            cd_l = os.path.join(self.old, _cd)
            cd_r = os.path.join(self.new, _cd)
            self.subdirs[_cd] = self.__class__(
                cd_l, cd_r, self.ignore, self.hide, self.shallow)

    # methodmap = dict(filecmp.dircmp.methodmap, subdirs=phase4, same_files=phase3,
    #                  diff_files=phase3, funny_files=phase3)

    @staticmethod
    def _process_hits(r_pth, in_lst):
        """Helper to compile the directory object lists."""
        # test print
        # print(f"_C pile {[r_pth.joinpath(entry) for entry in in_lst if in_lst]}")
        return [r_pth.joinpath(entry) for entry in in_lst if in_lst]

    def _amass_inst_hits(self):
        """Adds for every subdir instance the findings."""

        self.new_only_all.extend(
            self._process_hits(self.new_pt, self.new_only))
        self.diff_all.extend(
            self._process_hits(self.new_pt, self.diff_files))
        self.funny_all.extend(
            self._process_hits(self.new_pt, self.funny_files))
        # test print
        # print(f"_C amass diff {self.diff_all}  new o {self.new_only_all}")

    def _recursive_cmp(self):
        """Walks recursively through the dir tree."""
        self._amass_inst_hits()
        for self.cmp_inst in self.subdirs.values():
            self.cmp_inst._recursive_cmp()

    def diff_survey(self):
        """Delivers a complete list of the differences betwen the two trees.
        Entrys are pathlike abolute paths."""
        self.survey_lst = list(itertools.chain(
            self.new_only_all, self.diff_all, self.funny_all))

    def run_compare(self):
        """Controls the compare process and returns the outcome."""
        self._recursive_cmp()
        if self.funny_all:
            # perhaps do something with this e.g. deeper checks etc.
            pass
        self.diff_survey()

        self.count['dif_fl_found'] += len(self.diff_all)
        self.count['new_fl_found'] += len(self.new_only_all)
        self.count['fun_fl_found'] += len(self.funny_all)
        self.count['fl_total'] += len(self.survey_lst)
        self.inf(2, f"We found {self.count['dif_fl_found']} different"
                 f" files, {self.count['new_fl_found']} additional files"
                 f" in the new dir and {self.count['fun_fl_found']} non"
                 f"comparable files.")
        # self.inf(2, f"We found {D2p_Common.count['dif_fl_found']} different"
        #          f" files, {D2p_Common.count['new_fl_found']} additional files"
        #          f" in the new dir and {D2p_Common.count['fun_fl_found']} non"
        #          f"comparable files in {self.out_pt!s}.")

        return self.survey_lst


class D2p(D2p_Common):

    d2p_tmp_dir = None
    outdir = 'diff2patch_out'
    out_pt = None

    def __init__(self, survey_lst, new_pt, out_base_pt=None):
        self.survey_lst = survey_lst
        self._inp_pt = new_pt
        self.out_base_pt = new_pt.parent if not out_base_pt else pt(
            out_base_pt).resolve(strict=True)
        # test print
        # print(f"init out_base_pt: {self.out_base_pt}")

    def _exit(self):
        self.inf(0, "Exiting Diff2Patch.")
        for i in range(3, -1, -1):
            print(f"{D2p_Common.bg_red}{i}%{D2p_Common.std}", end='\r')
        sys.exit(0)

    def _dispose(self, outp=False):
        """Removes temporary content and the outdir if empty."""
        shutil.rmtree(self.d2p_tmp_dir)
        if outp:
            shutil.rmtree(self.out_pt)

    def _outp_check_user(self):
        self.inf(0, f"The output dir '{self.out_pt}' exists already. If we "
                 "proceed the content will be replaced!", m_sort='cau')
        while True:
            userinp = input("Type y/n : ").lower()
            if userinp in 'yes':
                break
            elif userinp in 'no':
                self._exit()
            # py 3.10 pattern matching
            # match userinp:
            #     case 'y' | 'yes':
            #         break
            #     case 'n' | 'no':
            #         self._exit()
        self._dispose(outp=True)

    def _make_output(self):
        """Constructs outdir and outpath."""
        self.out_pt = self.out_base_pt / self.outdir
        if self.out_pt.exists() and not self._void_dir(self.out_pt):
            self._outp_check_user()
        self._make_dirstruct(self.out_pt)

    def _pack_difftree(self, fmt):
        """Makes a tgz archive with the outdir content."""
        if fmt not in ['zip', 'tar']:
            fmt += 'tar'
        out_arch = self.out_pt.joinpath('d2p_patch')
        shutil.make_archive(out_arch, fmt, self.d2p_tmp_dir)

    def _mv_tmp2outdir(self):
        """Moves temporary content to output."""
        # NOTE: Converting 'src' to str to avoid bugs.python.org/issue32689
        # fixed in py 3.9 - move accepts now pathlike
        # TODO: if its long standard we use pathlikes as source
        # means users need py3.9+

        # FIXME: move does error if src exists in dst; how?
        for entry in self.d2p_tmp_dir.iterdir():
            shutil.move(str(entry), self.out_pt)

    def _gather_difftree(self):
        """Copys the differing objects to outdir."""
        # ignores = shutil.ignore_patterns('Thumbs.db', 'Thumbs.db:encryptable', 'desktop.ini', '.directory', '.DS_Store', 'log.txt', 'traceback.txt')

        for src in self.survey_lst:
            rel_src = src.relative_to(self._inp_pt)
            dst = self.d2p_tmp_dir.joinpath(rel_src)

            # test print
            # print(f"_cpy diff src {src} rel_src {rel_src} dst {dst}")

            if src.is_dir():
                shutil.copytree(src, dst, symlinks=False,  # ignore=ignores,
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
                     f"{self.out_pt!s}")

        # return self.out_pt


def _print_to(label, inp_lst, log_handler):

    logging.basicConfig(format='%(message)s', level=logging.INFO, handlers=log_handler)
    logging.info(f"\n{'-' * 80}\n{'#' * 10} {label} elements ###\n")

    # test print
    # print(f"INPUT {inp}")
    for entry in inp_lst:
        logging.info(f"{label} {str(entry)}")


def _print_diff(inp_lsts, report, outdir):
    """This prints the found differences to stdout and with -p option set also
    to a file. """
    out_f = outdir.joinpath('d2p_report.txt')
    out_f.unlink(missing_ok=True)

    log_con = logging.StreamHandler(sys.stdout)
    log_fle = logging.FileHandler(out_f, mode='a+')
    log_handler = (log_con, )  # logging.NullHandler()
    if report == 'file':
        log_handler = (log_fle, )
    elif report == 'both':
        log_handler = log_con, log_fle

    _print_to("new only", inp_lsts.new_only_all, log_handler)
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
    if not sys.version_info[:2] >= (3, 6):
        raise Exception("Must be executed in Python 3.6 or later.\n"
                        "You are running {}".format(sys.version))

    old = chk_indirs(cfg.old)
    new = chk_indirs(cfg.new)

    dtc = DirTreeCmp(old, new, shallow=cfg.indepth)
    survey = dtc.run_compare()

    # test print
    print(f"task d {cfg.dir} a {cfg.archive} r {cfg.report}")

    d2p = D2p(survey, new, out_base_pt=cfg.outpath)
    if cfg.report:
        d2p._make_output()
        _print_diff(dtc, cfg.report, d2p.out_pt)
    else:
        d2p.run()
        if cfg.dir:
            d2p._mv_tmp2outdir()
        elif cfg.archive:
            d2p._pack_difftree(cfg.archive)
        d2p._dispose()


if __name__ == "__main__":
    import timeit
    start = timeit.default_timer()

    main(_parse_args())

    print(f"Measured time for task: {timeit.default_timer() - start}")
