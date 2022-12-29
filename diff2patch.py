#!/usr/bin/python3
"""
Diff2patch is a tool which compares two directorys trees, e.g dir1/dir2, and
compiles a set of lists with the findings.
From this can be made another directory or archive, which contains all different or in the second dir added objects. A written report is also possible.
"""

import sys
import argparse
from pathlib import Path as pt
from copy import copy
import tempfile
import shutil
import logging
from time import strftime, localtime, sleep

# NOTE: A alternate to ctypes is apparently undocumented sys call to win which
# activates also color support
# https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/color
tty_colors = True
if sys.platform.startswith('win32'):
    if sys.getwindowsversion()[2] < 16257:

        try:
            from ctypes import windll
            # os.system('color')  # untested
        except ImportError:
            tty_colors = False
        else:
            k = windll.kernel32
            k.SetConsoleMode(k.GetStdHandle(-11), 7)


__title__ = 'Diff2patch'
__license__ = 'Apache 2.0'
__author__ = 'madeddy'
__status__ = 'Development'
__version__ = '0.8.0-alpha'

__all__ = ['Log', 'D2pCommon', 'DirTreeCmp', 'D2p']


# TODO:
class Log:
    """This configures and inits all logging for the module."""

    log = None
    colormap = {'rst': '\x1b[0m',  # reset
                'bld': '\x1b[1m',  # bold
                'ul': '\x1b[4m',  # underline
                'bln': '\x1b[5',  # blinking
                'rev': '\x1b[7m',  # reverse fg<->bg
                'blk': '\x1b[30m',  # black
                'ora': '\x1b[31m',  # orange
                'gre': '\x1b[32m',  # green
                'ylw': '\x1b[33m',  # yellow
                'blu': '\x1b[34m',  # blue
                'red': '\x1b[35m',  # red
                'cya': '\x1b[36m',  # cyan
                'b_blu': '\x1b[44;30m',  # background blue
                'b_red': '\x1b[45;30m',  # background red
                'b_wht': '\x1b[47;30m'}  # background white
    colormap.update((k, '') for k in colormap if not tty_colors)

    class ColorFormatter(logging.Formatter):
        """A sublassing of Formatter which adds colors to the loggers levelnames."""

        esc = '\x1b['  # escape sequence prefix
        rst = esc + '0'  # reset
        col_map = {
            'DEBUG': '1;37',  # bold, white
            'INFO': '32',  # green
            'NOTABLE': '34',  # blue
            'WARNING': '33',  # yellow
            'ERROR': '1;35',  # bold, red
            'CRITICAL': '30;41'}  # black, on red bg

        def __init__(self, fmt):
            super().__init__(fmt, style='{')

        def formatMessage(self, record):
            col_record = copy(record)
            levelname = col_record.levelname
            seq = self.col_map.get(levelname, 37)  # default white
            col_levelname = (f"{self.esc}{seq}m{levelname}{self.rst}m")
            col_record.levelname = col_levelname
            return self._style.format(col_record)

    class _ReportFilter(logging.Filter):
        """Allows in the handler where its used only output from  the `_print_proxy`
        method."""

        def __init__(self, reverse=False):
            self.rev = reverse

        def filter(self, record):
            res = record.funcName == '_print_proxy'
            return res if not self.rev else not res

    @classmethod
    def _c(cls, key):
        """tf = Ansi Escape Sequence"""
        return cls.colormap[key]

    def _notable(self, msg, *args, **kwargs):
        """Adds a custom logging level 'NOTABLE' with severity level 25, between
        info(20) and warning(30)."""
        if self.isEnabledFor(25):
            self._log(25, msg, args, **kwargs)

    @classmethod
    def init_log(cls, report=None, output_pt=None, logfile=True, loglevel='NOTABLE'):
        """
        Does setup the logging behavior.
        This includes the functionality for the output of the diff report to all targets
        and terminal meassages.
        """
        logging.addLevelName(25, 'NOTABLE')
        logging.Logger.notable = cls._notable
        cls.log = logging.getLogger("D2P")

        # TODO: add another infolevel name like "extra info", info+
        # Add console handler always. Use custom formatter if tty colors available.
        con_h = logging.StreamHandler()
        if not report or report == 'file':
            con_h.addFilter(cls._ReportFilter(reverse=True))
        con_h.setLevel(loglevel)
        _formatter = cls.ColorFormatter if tty_colors else logging.Formatter
        con_f = _formatter(
            "[{name}][{levelname:>8s}] >> {message}")
        con_h.setFormatter(con_f)
        cls.log.addHandler(con_h)

        # Add log-file handler if not disabled in CLI
        if logfile:
            log_fh = logging.FileHandler(
                pt(__file__).parent.resolve().joinpath('d2p.log'))
            log_fh.addFilter(cls._ReportFilter(reverse=True))
            log_fh.setLevel('WARNING')
            log_ff = logging.Formatter(
                "{asctime} - {name} - {levelname:>8s} - {message} - {filename}:"
                "{lineno:d}", style='{')
            log_fh.setFormatter(log_ff)
            cls.log.addHandler(log_fh)

        # Add report-file handler if enabled in CLI
        if report in ('file', 'both'):
            rep_fn = f'd2p_report_{strftime("%d.%b.%Y_%H:%M:%S", localtime())}.txt'
            outf_pt = output_pt.joinpath(rep_fn)
            rep_fh = logging.FileHandler(outf_pt, mode='a+', delay=True)
            rep_fh.addFilter(cls._ReportFilter())
            rep_fh.setLevel('INFO')
            rep_ff = logging.Formatter("{message}", style='{')
            rep_fh.setFormatter(rep_ff)
            cls.log.addHandler(rep_fh)


class D2pCommon:
    """This provides shared methods and variables for child classes."""

    name = __title__
    count = {'diff_found': 0,
             'new_found': 0,
             'sketchy_found': 0,
             'fl_total': 0,
             'fl_done': 0,
             'patch_size': None}

    @classmethod
    def telltale(cls, fraction, total, obj):
        """Returns a percentage-meter like output for use in tty."""
        return (f"[{cls._c('b_blu')}{fraction / float(total):05.1%}"
                f"{cls._c('rst')}] {obj!s:>4}")

    @classmethod
    def _exit(cls):
        cls.log.notable("Exiting Diff2Patch.\n")
        for i in range(10, -1, -1):
            cls.log.warning(
                f"{cls._c('b_red')}< {i} >{cls._c('rst')} \x1b[10D\x1b[1A\x1b[K")
            sleep(0.2)
        sys.exit(0)


            print(textwrap.fill(msg, width=90, initial_indent=ind1,
                  subsequent_indent=ind2))




class DirTreeCmp(D2pCommon, Log):
    """
    This class compiles a diff object list of two given dirs for comparison.
    A modified version of dircmp is used where shallow can be choosen.

    new_only_all:   Files which exist only in the dir-tree of "new"
    diff_all:       Differing files of the two dir-trees
    funny_all:      Unidentified files of the dir-trees
    survey_lst:     All three lists above compiled in one
    """
    new_only_all = []
    diff_all = []
    funny_all = []
    survey_lst = []

    def __init__(self, old, new, ignore=None, hide=None, shallow=True):
        self.cmp_inst = None
        super().__init__(old, new, ignore, hide)
        self.left = pt(old).resolve()
        self.right = pt(new).resolve()
        self.ignore.extend([
            'Thumbs.db', 'Thumbs.db:encryptable', 'desktop.ini', '.directory',
            '.DS_Store', 'log.txt', 'traceback.txt'])
        self.shallow = shallow

    def phase3(self):
        self.same_files, self.diff_files, self.funny_files = filecmp.cmpfiles(
            self.left, self.right, self.common_files, self.shallow)

    def phase4(self):
        self.subdirs = {}
        for _cd in self.common_dirs:
            # cd_l = os.path.join(self.left, _cd)
            # cd_r = os.path.join(self.right, _cd)
            cd_l = self.left.joinpath(_cd)
            cd_r = self.right.joinpath(_cd)
            self.subdirs[_cd] = self.__class__(
                cd_l, cd_r, self.ignore, self.hide, self.shallow)

    filecmp.dircmp.methodmap.update(
        same_files=phase3, diff_files=phase3, funny_files=phase3, subdirs=phase4)

    def _process_hits(self, in_lst):
        """Helper to compile the directory object lists."""
        return [self.right.joinpath(entry) for entry in in_lst if in_lst]

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
            self.log.warning("Well shit! We have UFO's! < unidentified file objects >")

        self.cmp_survey = {'dir1': self.dir1,
                           'dir2': self.dir2,
                           'new': self.dir2_only_all,
                           'diff': self.diff_all,
                           'sketchy': self.sketchy_all}

        self.count['diff_found'] += len(self.diff_all)
        self.count['new_found'] += len(self.dir2_only_all)
        self.count['sketchy_found'] += len(self.sketchy_all)
        self.count['fl_total'] += sum(list(self.count.values())[:3])
        self.log.info(f"We found {self.count['diff_found']} different files,"
                      f" {self.count['new_found']} additional files in directory 2"
                      f" and {self.count['sketchy_found']} non comparable files.")

        return self.cmp_survey

        self.count['dif_fl_found'] += len(self.diff_all)
        self.count['new_fl_found'] += len(self.new_only_all)
        self.count['fun_fl_found'] += len(self.funny_all)
        self.count['fl_total'] += len(self.survey_lst)
        self.inf(2, f"We found {self.count['dif_fl_found']} different files,"
                 f" {self.count['new_fl_found']} additional files in the right"
                 f" dir and {self.count['fun_fl_found']} non comparable files.")

        return self.survey_lst


class D2p(D2pCommon, Log):
    """
    Class which backups a list of given path objects to a target dir. Can be
    done as pure directory tree or as archive of given type.

    d2p_tmp_dir:    Temporary dir for the patch files before theyre moved to
                    "outdir"
    outdir:         Name of the dir where the patch files are placed
    output_pt:      The full path for the patch/report files; includes out dir
                    as last path element
    """
    d2p_tmp_dir = None
    outdir = 'diff2patch_out'
    output_pt = None


    def _print_proxy(self, header, label, survey_lst):
        """Helper func which prints the report variant out."""
        self.log.notable(f"\n{'-' * 80}\n{'#' * 10} {header} elements ###\n")

        for entry in survey_lst:
            self.log.notable(f"{label}{str(entry)}")

    def print_diff(self):
        """This manages the printout of the diff report."""

        self._print_proxy(
            "Diff2patch report",
            '',
            [f"Comparison directories >>"
             f" FROM: {self.cmp_survey['dir1']} TO: {self.cmp_survey['dir2']}"])
        self._print_proxy(
            "Directory-2-only",
            "New: ",
            self.cmp_survey['new'])
        self._print_proxy(
            "Different",
            "Diff: ",
            self.cmp_survey['diff'])
        self._print_proxy(
            "Unidentified",
            "Sketchy: ",
            self.cmp_survey['sketchy'])

    def _dispose(self, outp=False):
        """Removes temporary content and the output_pt if empty."""
        if self.d2p_tmp_dir:
            shutil.rmtree(self.d2p_tmp_dir)
        if outp:
            shutil.rmtree(self.output_pt)

        self.log.notable(
            "Archiving files. This can take a while depending on sys speed,"
            " archive type and patch size.")
        self.log.warning(f"{self._c('bln')}Working...{self._c('rst')}")
            self.log.info(f"{self.telltale(num, tot, obj)}")
    @staticmethod
    def _void_dir(dst):
        """Checks if given directory has content."""
        return not any(dst.iterdir())

    @classmethod
    def _make_dirstruct(cls, dst):
        """Constructs any needet output directorys if they not already exist."""
        if not dst.exists():
            self.log.info(f"Creating directory structure for: {dst}")
            dst.mkdir(parents=True, exist_ok=True)

    def _outp_check_user(self):
        """This offers the choice to proceed and erase the old output-dir or to quit."""
        self.log.warning(f"The output dir '{self.output_pt}' exists already. If"
                         " we proceed the content will be replaced!")
        while True:
            userinp = input("Proceed? Choose y|yes or n|no : ").lower()

            match userinp:
                case 'y' | 'yes':
                    break
                case 'n' | 'no':
                    self._exit()
                case _:
                    self.log.warning("Not a allowed choice! Try again.")

        self._dispose(outp=True)

    def _make_output(self):
        """Constructs outdir path and structure."""
        self.output_pt = self.out_base_pt / self.outdir
        if self.output_pt.exists() and not self._void_dir(self.output_pt):
            self._outp_check_user()
        self._make_dirstruct(self.output_pt)

    def _pack_difftree(self, fmt):
        """Constructs a archive with the outdir content."""
        if fmt not in ['zip', 'tar']:
            fmt += 'tar'
        out_arch = self.output_pt.joinpath('d2p_patch')
        shutil.make_archive(out_arch, fmt, self.d2p_tmp_dir)

    def _mv_tmp2outdir(self):
        """Moves temporary content to real output."""
        # FIXME: move does error if src exists in dst; how?
        for entry in self.d2p_tmp_dir.iterdir():
            shutil.move(entry, self.output_pt)

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

    def calc_patch_data(self):
        """Prepairs the patch list from the diff-survey dict and lets mesasure the
        expected patch size."""
        self.patch_lst = [*self.cmp_survey['new'],
                          *self.cmp_survey['diff'],
                          *self.cmp_survey['sketchy']]
        self.get_patchsize(self.patch_lst)

    def run(self):
        """Controls and executes the collection of files in tmp."""
        self.d2p_tmp_dir = pt(tempfile.mkdtemp(
            prefix='Diff2Patch.', suffix='.tmp'))
        self._make_output()
        self._gather_difftree()

        if self._void_dir(self.d2p_tmp_dir):
            self.log.warning("No files for a patch collected.")
        else:
            self.log.info(f"Collected {self.count['fl_total']} patch files.")


def chk_indir(inp):
    """Helper to check the input directorys for validity."""
    if not pt(inp).resolve(strict=True).is_dir():
        Log.log.critical(
            f"Input needs to be a directory path: {inp}", exc_info=True)
        raise NotADirectoryError
    return pt(inp)


def _parse_args():
    """Gets the args if CLI is used."""
    aps = argparse.ArgumentParser(
        description='Generates a diff patch or overview of two given directory'
        ' structures.')
    aps.add_argument(
        'old',
        action='store',
        type=chk_indir,
        help='Old/left directory')
    aps.add_argument(
        'new',
        action='store',
        type=chk_indir,
        help='New/right directory')
    opts = aps.add_mutually_exclusive_group(required=True)
    opts.add_argument(
        '-d', '--dir',
        action='store_true',
        help='Outputs the diff as a directory structure.')
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
        type=pt,
        help='Output path name for the diff result. Defaults to the parent dir'
        ' of <new> if not given.')
    aps.add_argument(
        '-i', '--indepth',
        action='store_true',
        help='Compares the files content instead statinfos like size, date of'
        ' last change.')
    aps.add_argument(
        '-n', '--no_log',
        action='store_false',
        help='Deactivates the use of a logfile in the script path.')
    aps.add_argument(
        '-l', '--loglevel',
        type=str,
        default='NOTABLE',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        help='Set minimum log-level for the console. Default is "info". Use "warning"'
        ' or higher to reduce output.')
    aps.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s : { __title__} {__version__}')
    return aps.parse_args()


def main(cfg):
    """Main block of the module with functionality for use on CLI."""
    if not sys.version_info[:2] >= (3, 10):
        Log.log.critical("Must be executed in Python 3.10 or above.\n"
                         "You are running {}".format(sys.version), exc_info=True)
        raise Exception

    dlg = Log
    try:
        dlg.init_log(report=cfg.report, output_pt=out_base_pt, logfile=cfg.no_log,
                     loglevel=cfg.loglevel.upper())
        dlg.log.setLevel('DEBUG')
    except Exception:
        dlg.log.critical("Problem while initialize logging.", exc_info=True)
        raise Exception

    mode = 'directory' if cfg.dir else 'archive' if cfg.archive else 'report'
    dlg.log.notable(
        f"{dlg._c('b_blu')}Start of diff2patch in {mode} mode."
        f"{dlg._c('rst')}\n"
        f"Comparing > DIR 1:{cfg.dir1} DIR 2:{cfg.dir2}")

    # TODO: Add verbosity functionallity to classes
    dtc = DirTreeCmp(cfg.old, cfg.new, shallow=cfg.indepth)
    survey = dtc.run_compare()

    d2p = D2p(survey, cfg.new, out_base_pt=cfg.outpath)
    # control print
    print(f"config arch:  {cfg}")

    if cfg.dir or cfg.archive:
        d2p.run()
        try:
            if cfg.dir:
                d2p._mv_tmp2outdir()
            elif cfg.archive:
                d2p._pack_difftree(cfg.archive)
            d2p._dispose()
        except OSError:
            d2p.log.error(
                "Encountered a problem as the output directory / archive was moved to"
                " destination or at the removal of the tempdir structure.",
                exc_info=True)
        else:
            d2p.log.notable("The patch result of the diff task was written to path"
                            f" {d2p.output_pt}.")
    else:
        d2p.print_diff()
        d2p.log.notable("The diff report is done.")

    d2p.log.notable(f"All {d2p.count['fl_total']} files of the patch content measure"
                    f" to a unpacked size of {d2p.count['patch_size']}.")
    d2p.log.info("Choosen diff2patch task completed.")
    d2p._exit()


if __name__ == "__main__":
    main(_parse_args())
