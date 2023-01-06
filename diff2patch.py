#!/usr/bin/python3
"""
Diff2patch is a tool which compares two directorys trees, e.g dir1/dir2, and
compiles a set of lists with the findings.
From this result can another directory or archive constructed, which contains all different or in the second dir added objects. A written report is also possible.

Parts of the code of this tool shadows with changes to it pythons filecmp module.
"""

import sys
import argparse
from types import GenericAlias
from os import curdir, pardir
from pathlib import Path as pt
from operator import attrgetter
from copy import copy
import stat as st
import tempfile
import shutil
import logging
from time import strftime, localtime, sleep

# NOTE: The os.system alternate to ctypes is apparently a undocumented sys call to win
# which activates also color support
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
__version__ = '0.23.0-alpha'
__url__ = "https://github.com/madeddy/diff2patch"


__all__ = ['Log', 'D2pCommon', 'DirTreeCmp', 'D2p']


# TODO:
# test patch calc functionality some more
# IDEA: Add abbility to output other cmp lists(like filecmp)

class Log:
    """This configures and initiates all logging functionality for the module."""

    log = None
    colormap = {'rst': '\x1b[0m',  # reset
                'bld': '\x1b[1m',  # bold
                'ul': '\x1b[4m',  # underline
                'bln': '\x1b[5m',  # blinking
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
                'b_wht': '\x1b[47;30m',  # background white
                'ret': '\x1b[10D\x1b[1A\x1b[K'}  # write on same line: (xD - x rows left,
    # xA - x lines up, K - erase line)

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
        """
        Filter subclass which restricts the output of the handler where it is used to a
        certain method. Can be reversed.
        """

        def __init__(self, reverse=False):
            self.rev = reverse

        def filter(self, record):
            """Determines if a message orginates from the `_print_proxy` method."""
            res = record.funcName == '_print_proxy'
            return res if not self.rev else not res

    @classmethod
    def _c(cls, key):
        """Delivers the correct ansi escape sequence to a color/effect name(key) from a
        dict."""
        return cls.colormap[key]

    def _notable(self, msg, *args, **kwargs):
        """
        Adds a custom logging level 'NOTABLE' with severity level 25, between
        info(20) and warning(30).
        """
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
             'dirs_total': 0,
             'patch_size': None}

    @classmethod
    def telltale(cls, fraction, total, obj):
        """
        Returns a percentage-meter like output for use in tty.
        Arguments:
            fraction:   Count of already worked objects; start usually with zero
            total:      The full amount objects to work through
            obj:        The current object in work
        """
        return (f"[{cls._c('b_blu')}{fraction / float(total):05.1%}"
                f"{cls._c('rst')}] {obj!s:>4}")

    @classmethod
    def _exit(cls):
        cls.log.notable("Exiting Diff2Patch.\n")
        for i in range(10, -1, -1):
            cls.log.warning(
                f"{cls._c('b_red')}< {i} >{cls._c('rst')} {cls._c('ret')}")
            sleep(0.2)
        sys.exit(0)

    @staticmethod
    def check_inpath(inp, strict=True):
        """Helper to check if given path exist."""
        return pt(inp).resolve(strict)


class DirTreeCmp(D2pCommon, Log):
    """
    This class compiles a diff-object dictionary with multiple list comparison results of
    two given dirs.
    A modified version of dircmp is used where shallow can be choosen.

    dir1_only_all:  Files which exist only in the dir-tree of "dir1"  # unused for now
    dir2_only_all:  Files which exist only in the dir-tree of "dir2"
    mutual_all:     Mutual files of the two dir-trees  # unused for now
    diff_all:       Differing files of the two dir-trees
    sketchy_all:    Unidentified files of the dir-trees
    mutual_dirs:    Mutual dirs of the two dir-trees  # unused for now
    mutual_sk_dirs: Unidentified mutual dirs  # unused for now
    cmp_survey:     All three lists needed for a patch(dir2 only, diff, sketchy files)
                    compiled together in a dict
    """

    bufsize = 8 * 1024
    _cache = {}
    def_hide = [curdir, pardir]
    def_ignore = [
        'RCS', 'CVS', 'tags', '.git', '.hg', '.bzr', '_darcs', '__pycache__',
        'Thumbs.db', 'Thumbs.db:encryptable', 'desktop.ini', '.directory', '.DS_Store',
        'log.txt', 'traceback.txt']

    # dir1_only_all = list()
    dir2_only_all = list()
    # mutual_all = list()
    diff_all = list()
    sketchy_all = list()
    # mutual_dirs = list()
    # sketchy_dirs = list()
    cmp_survey = dict()

    def __init__(self, dir1, dir2, ignore=None, hide=None, shallow=True):
        self.cmp_inst = None
        self.dir1 = self.check_inpath(dir1)
        self.dir2 = self.check_inpath(dir2)
        self.hide = DirTreeCmp.def_hide if not hide else hide
        self.ignore = DirTreeCmp.def_ignore if not ignore else ignore
        self.skip = self.hide + self.ignore
        self.shallow = shallow

    @classmethod
    def _deep_cmp(cls, f1, f2):
        """Compares two files content in chunks."""
        with f1.open("rb") as of1, f2.open("rb") as of2:
            while True:
                b1 = of1.read(cls.bufsize)
                b2 = of2.read(cls.bufsize)
                if b1 != b2:
                    return False
                if not b1:
                    return True

    @classmethod
    def _get_stat(cls, inp):
        """Returns chosen stat modes for a path object."""
        modes = attrgetter('st_mode', 'st_size', 'st_mtime')
        try:
            return modes(inp.stat()), True
        except OSError:
            cls.log.error(f"Could not stat {inp}!")
            return None, False

    def cmp_file(self, f1, f2, shallow=True):
        """
        Compare two files.

        Arguments:
        f1 -- First file name
        f2 -- Second file name
        shallow -- Just check stat signature (do not read the files). defaults to True.
        Return value:   True if the files are the same, False otherwise.

        This function uses a cache for past comparisons and the results,
        with cache entries invalidated if their stat information
        changes.
        """

        s1, status = self._get_stat(f1)
        s2, status = self._get_stat(f2)
        if not status:
            return False
        if not st.S_ISREG(s1[0]) or not st.S_ISREG(s2[0]):
            return False
        if shallow and s1 == s2:
            return True
        if s1[1] != s2[1]:
            return False

        outcome = self._cache.get((f1, f2, s1, s2))
        if outcome is None:
            outcome = self._deep_cmp(f1, f2)
            if len(self._cache) > 100:
                self._cache.clear()
            self._cache[f1, f2, s1, s2] = outcome
        return outcome

    def cmp_dirfiles(self, d1, d2, mutual, shallow=True):
        """
        Compares mutual files in two directories.

        d1, d2 -- directory names
        mutual -- list of file names found in both directories
        shallow -- if true, do comparison based solely on stat() information
        Returns a tuple of three lists:
        files that compare equal
        files that are different
        filenames that aren't regular files.
        """
        res = ([], [], [])
        for x in mutual:
            f1x = d1.joinpath(x)
            f2x = d2.joinpath(x)
            try:
                cmp_res = abs(self.cmp_file(f1x, f2x, shallow))
            except OSError:
                cmp_res = 2
            res[cmp_res].append(x)
        return res

    def _get_dirlist(self, inp_pt):
        """
        Helper which returns to phase0 a list of all directory entrys without the
        occurences in skip.
        """
        filtered_dl = [
            entry.relative_to(inp_pt) for entry in inp_pt.iterdir()
            if entry not in self.skip]
        filtered_dl.sort()
        return filtered_dl

    def phase0(self):
        """
        Lists for both dirs the content and filters excludet names out. Doesn't traverse
        inside subdirectories.
        """
        self.dir1_list = self._get_dirlist(self.dir1)
        self.dir2_list = self._get_dirlist(self.dir2)

    def phase1(self):
        """Computes lists with mutual and non mutual files and dirs."""
        d1_set = set(self.dir1_list)
        d2_set = set(self.dir2_list)

        self.mutual = [entry for entry in d1_set.intersection(d2_set)]
        self.dir1_only = [entry for entry in d1_set.difference(d2_set)]
        self.dir2_only = [entry for entry in d2_set.difference(d1_set)]

    def phase2(self):
        """Distinguish between mutual content files or directories or unidentified."""
        self.mutual_dirs = list()
        self.mutual_files = list()
        self.mutual_sketchy = list()

        for x in self.mutual:
            path_1 = self.dir1.joinpath(x)
            path_2 = self.dir2.joinpath(x)

            stat_1, status = self._get_stat(path_1)
            stat_2, status = self._get_stat(path_2)

            if status:
                type_1 = st.S_IFMT(stat_1[0])
                type_2 = st.S_IFMT(stat_2[0])
                if type_1 != type_2:
                    self.mutual_sketchy.append(x)
                elif st.S_ISDIR(type_1):
                    self.mutual_dirs.append(x)
                elif st.S_ISREG(type_1):
                    self.mutual_files.append(x)
                else:
                    self.mutual_sketchy.append(x)
            else:
                self.mutual_sketchy.append(x)

    def phase3(self):
        """Detects and yields the differences between the mutual files of a directory."""
        self.diff_files, self.same_files, self.sketchy_files = self.cmp_dirfiles(
            self.dir1, self.dir2, self.mutual_files, self.shallow)

    def phase4(self):
        """
        This method executes a self-instanciating recursive iteration into every pair of bilateral subdirectorys.
        """
        self.subdirs = {}
        for _cd in self.mutual_dirs:
            cd_l = self.dir1.joinpath(_cd)
            cd_r = self.dir2.joinpath(_cd)
            self.subdirs[_cd] = self.__class__(
                cd_l, cd_r, self.ignore, self.hide, self.shallow)

    def _process_hits(self, in_lst):
        """Helper to compile the directory object lists."""
        return [self.dir2.joinpath(entry) for entry in in_lst if in_lst]

    def _gather_inst_hits(self):
        """Adds for every subdir instance the findings."""
        self.dir2_only_all.extend(self._process_hits(self.dir2_only))
        self.diff_all.extend(self._process_hits(self.diff_files))
        self.sketchy_all.extend(self._process_hits(self.sketchy_files))

    def _recursive_cmp(self):
        """
        Recursively traverses into bilateral subdirectorys, by calling for every level
        below the last a new comparison instance and collects the outcome of every new
        directory.
        """
        self._gather_inst_hits()
        for self.cmp_inst in self.subdirs.values():
            self.cmp_inst._recursive_cmp()

    def run_compare(self):
        """Controls some steps of compare process and returns the outcome."""
        self._recursive_cmp()
        if self.sketchy_all:
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
        self.log.info(f"We found {self.count['diff_found']} different files,"
                      f" {self.count['new_found']} additional files in directory 2"
                      f" and {self.count['sketchy_found']} non comparable files.")

        return self.cmp_survey

    methodmap = dict(
        dir1_list=phase0, dir2_list=phase0,
        mutual=phase1, dir1_only=phase1, dir2_only=phase1,
        mutual_dirs=phase2, mutual_files=phase2, mutual_sketchy=phase2,
        same_files=phase3, diff_files=phase3, sketchy_files=phase3,
        subdirs=phase4)

    def __getattr__(self, attr):
        if attr not in self.methodmap:
            raise AttributeError(attr)
        self.methodmap[attr](self)
        return getattr(self, attr)

    __class_getitem__ = classmethod(GenericAlias)


class D2p(D2pCommon, Log):
    """
    Class which backups a list of given path objects to a target dir. Can be
    done as pure directory tree or as archive of given type.

    d2p_tmp_dir:    Temp dir for patch files before they're moved to "output_pt"
    outdir_name:    New dir where the patch files are placed
    output_pt:      The full path for the patch/report files; includes outdir_name
                    as last path element
    """

    d2p_tmp_dir = None
    outdir_name = 'diff2patch_out'
    output_pt = None

    def __init__(self, cmp_survey, dir2_pt, out_base_pt=None, mock_mode=False):
        self.cmp_survey = cmp_survey
        self.patch_lst = list()
        self.inp_pt = self.check_inpath(dir2_pt)
        self.out_base_pt = self.inp_pt.parent if not out_base_pt else self.check_inpath(
            out_base_pt)
        self.mock_mode = mock_mode

    def _calc_filedata(self, inp, only_size=False):
        """Returns the size of a pathlike in bytes."""
        if inp.is_file() and not inp.is_symlink():
            if not only_size:
                self.count['fl_total'] += 1
            return inp.stat(follow_symlinks=False).st_size
        elif inp.is_dir():
            if not only_size:
                self.count['dirs_total'] += 1
        else:
            self.log.warning("Irregular path entry while calculating patch-data:"
                             f"{inp}")
        return 0

    def calc_patch_data(self, inp, only_size=False):
        """
        Measures and returns the size of the patch in binary units.
        Input must be a list of pathlikes as values.
        """
        size = 0
        try:
            if not only_size:
                for ele in inp.rglob('*'):
                    size += self._calc_filedata(ele)
            else:
                for entry in inp:
                    if entry.is_dir():
                        for ele in entry.rglob('*'):
                            size += self._calc_filedata(ele, only_size=True)
                    else:
                        size += self._calc_filedata(entry, only_size=True)

        except Exception:
            self.log.error("Encountered a problem while measuring the patchsize.",
                           exc_info=True)
            self.count['patch_size'] = 'ERROR'
        else:
            for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'):
                if size < 1024:
                    break
                size /= 1024
            self.count['patch_size'] = f"{size:.2f}{unit}"

    def _print_proxy(self, header=None, inf=None, label=None, survey_lst=None):
        """Helper func which prints the report variant out."""
        if header:
            self.log.notable(
                f"\n{'-' * 100}\n{'#' * 10} {header} ###\n")
        if inf:
            self.log.notable(f"{inf}")

        if survey_lst:
            survey_lst.sort()
            for num, entry in enumerate(survey_lst, start=1):
                self.log.notable(f"{label}#{num} > {str(entry)}")
        elif survey_lst is not None:
            self.log.notable(f"{label}No entrys.")

    def print_diff(self):
        """
        This manages all necesary steps for the printout of the diff report.
        Executes patch size calculation again, because the mock dirtree cannot give
        correct size info in the first run.
        """
        self.calc_patch_data(self.patch_lst, only_size=True)

        self._print_proxy(
            header="Diff2patch report",
            inf=f"Comparison directories >> FROM: {self.cmp_survey['dir1']}"
                f" TO: {self.cmp_survey['dir2']}")
        self._print_proxy(
            header="Directory-2-only elements",
            label="New: ",
            survey_lst=self.cmp_survey['new'])
        self._print_proxy(
            header="Different elements",
            label="Diff: ",
            survey_lst=self.cmp_survey['diff'])
        self._print_proxy(
            header="Unidentified",
            label="Sketchy elements: ",
            survey_lst=self.cmp_survey['sketchy'])
        self._print_proxy(
            header="End of the D2P report",
            inf="Please note: The report has always less path elements as the complete"
            " dir-tree, because only the minimal mutual path is stored.")

    def _dispose(self, outp=False):
        """Removes temporary dir/content and the output_pt."""
        if self.d2p_tmp_dir:
            shutil.rmtree(self.d2p_tmp_dir)
        if outp:
            shutil.rmtree(self.output_pt)

    def _pack_difftree(self, fmt):
        """Constructs a archive with the outdir content."""
        if fmt not in ['zip', 'tar']:
            fmt += 'tar'
        out_archive = self.output_pt.joinpath('d2p_patch')
        self.log.notable(
            "Archiving files. This can take a while depending on sys speed,"
            " archive type and patch size.")
        self.log.warning(f"{self._c('bln')}Working...{self._c('rst')}")
        shutil.make_archive(out_archive, fmt, self.d2p_tmp_dir, logger=self.log)

    def _mv_tmp2outdir(self):
        """Moves temporary content to real output."""
        # FIXME: move does error if src exists in dst; how?
        fl_done = 0
        for entry in self.d2p_tmp_dir.iterdir():
            fl_done += 1
            num, tot, obj = fl_done, self.count['fl_total'], entry

            self.log.info(f"{self.telltale(num, tot, obj)}")
            shutil.move(entry, self.output_pt)

    @staticmethod
    def _void_dir(dst):
        """Checks if given directory has content."""
        return not any(dst.iterdir())

    def _make_dirstruct(self, dst):
        """Constructs any needet output directorys if they not already exist."""
        if not dst.exists():
            self.log.info(f"Creating directory structure for: {dst}")
            dst.mkdir(parents=True, exist_ok=True)

    def _check_output_exists(self):
        """Tests if the d2p-output already exists and if, checks with the user how to
        proceed. Choices are to erase the old output-dir or to quit."""
        if self.output_pt.exists() and not self._void_dir(self.output_pt):
            self.log.warning(f"The output dir '{self.output_pt}' exists already. If"
                             " we proceed the content will be replaced!")

            while True:
                userinp = input("Choose y|yes to proceed or n|no to exit : ").lower()
                match userinp:
                    case 'y' | 'yes':
                        break
                    case 'n' | 'no':
                        self._exit()
                    case _:
                        self.log.warning("Not a allowed choice! Try again.")

            self._dispose(outp=True)

    @staticmethod
    def _mockcopy(_, dst):
        """
        This is a mock of the copy function for use in shutil.copytree, which produces
        zero-size files to save time and other ressources.

        We construct a complete mock-tree representation of the patch because in
        report-mode we cannot calculate the file/dir count correct, since `dirtreecmp`
        yields just parts of a dirtree as `patch_list`. This way we circumvent the
        problem and the output is simply thrown away after use.
        """
        pt(dst).touch()
        return dst

    def _gather_patchtree(self):
        """Copys the patch content with relative paths to the temp-dir."""
        for src in self.patch_lst:
            rel_src = src.relative_to(self.inp_pt)
            dst = self.d2p_tmp_dir.joinpath(rel_src)

            if src.is_dir():
                if not self.mock_mode:
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copytree(src, dst, dirs_exist_ok=True,
                                    copy_function=self._mockcopy)
            elif src.is_file():
                self._make_dirstruct(dst.parent)
                if not self.mock_mode:
                    shutil.copy2(src, dst)
                else:
                    dst.touch()

    def compile_patch_list(self):
        """Prepairs the patch list from the diff-survey dict."""
        self.patch_lst = [*self.cmp_survey['new'],
                          *self.cmp_survey['diff'],
                          *self.cmp_survey['sketchy']]

    def run(self):
        """Controls the process of generating a patch from the diff-patch lists."""
        self.d2p_tmp_dir = pt(
            tempfile.mkdtemp(prefix='Diff2Patch.', suffix='.tmp'))
        self.log.debug(f"The temporary dir {self.d2p_tmp_dir} was successful made.")

        if not self.mock_mode:
            self.output_pt = self.out_base_pt / self.outdir_name
            self._check_output_exists()
            self._make_dirstruct(self.output_pt)

        self.compile_patch_list()
        self._gather_patchtree()
        self.calc_patch_data(self.d2p_tmp_dir)

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
        description='Generates a diff-patch or overview of two given directory'
        ' structures.')
    aps.add_argument(
        'dir1',
        action='store',
        type=chk_indir,
        help='Dir 1/left directory')
    aps.add_argument(
        'dir2',
        action='store',
        type=chk_indir,
        help='Dir 2/right directory')
    opts = aps.add_mutually_exclusive_group(required=True)
    opts.add_argument(
        '-d', '--dir',
        action='store_true',
        help='Outputs the diff as a directory structure.')
    opts.add_argument(
        '-a', '--archive',
        type=str,
        choices=('xz', 'gz', 'bz', 'zip', 'tar'),
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
        ' of <dir2> if not given.')
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
        choices=['DEBUG', 'INFO', 'NOTABLE', 'WARNING', 'ERROR', 'CRITICAL'],
        help='Set minimum log-level for the console. Default is "notable". Use "warning"'
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
    out_base_pt = cfg.dir2.parent
    try:
        dlg.init_log(report=cfg.report, output_pt=out_base_pt, logfile=cfg.no_log,
                     loglevel=cfg.loglevel.upper())
        dlg.log.setLevel('DEBUG')
    except Exception:
        dlg.log.critical("Problem while initializing logging.", exc_info=True)
        raise Exception

    dlg.log.debug(f"ARGPARSE cfg: {cfg}")

    mode = 'directory' if cfg.dir else 'archive' if cfg.archive else 'report'
    dlg.log.notable(
        f"{dlg._c('b_blu')}Start of diff2patch in {mode} mode."
        f"{dlg._c('rst')}\n"
        f"Comparing > DIR 1:{cfg.dir1} DIR 2:{cfg.dir2}")

    dtc = DirTreeCmp(cfg.dir1, cfg.dir2, shallow=cfg.indepth)
    survey = dtc.run_compare()

    mock_mode = True if cfg.report else False
    d2p = D2p(survey, cfg.dir2, out_base_pt=cfg.outpath, mock_mode=mock_mode)
    d2p.run()

    if cfg.dir or cfg.archive:
        try:
            if cfg.dir:
                d2p._mv_tmp2outdir()
            elif cfg.archive:
                d2p._pack_difftree(cfg.archive)
        except OSError:
            d2p.log.error(
                "Encountered a problem as we attempted to move the patch to"
                " destination.", exc_info=True)
        else:
            d2p.log.notable("The patch result of the diff task was written to path"
                            f" {d2p.output_pt}.")
    else:
        d2p.print_diff()
        diff_target = cfg.report if cfg.report != "both" else "terminal and file"
        d2p.log.notable("The composition of the diff report is done and was written to"
                        f" {diff_target}.")

    try:
        d2p._dispose()
    except OSError:
        dlg.log.error(
            "Problem while trying to remove the tempdir structure.", exc_info=True)

    d2p.log.notable(
        f"The patch content with {d2p.count['fl_total']} files and"
        f" {d2p.count['dirs_total']} directories measures to a unpacked size of"
        f" {d2p.count['patch_size']}.")
    d2p.log.info("Choosen diff2patch task completed.")
    d2p._exit()


if __name__ == "__main__":
    main(_parse_args())
