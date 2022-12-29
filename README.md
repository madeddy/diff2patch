# diff2patch
A python tool to compare two directorys and composes a survey-list with all found
differences. These can then used to:
- give a report in different forms:
  - written to terminal
  - written to a text-file
  - both 
- compose a patch with all different and in dir2 new files
Said patch content can be written as simple directory or archive.

## Dependencys
- python 3.10 or newer
### Optional
For terminal colors in info messages: With early `Windows 10` and before could it be
necessary to change a few config settings to make it work.

Colors just a fancfull addition and it works without it. Some people might want it. There
are also other ways like _ansicon_ or the use of Windows terminal, where ANSI already
integrated is. (code changes needed)

## Usage
### Command line parameter overview
```
diff2patch.py [-h] (-d | -a {xz,gz,bz2,zip,tar} | -r {console,file,both}) [-o OUTPATH]
[-i] [-n] [-l] [--version] dir1 dir2

Generates a diff patch or overview of two given directory structures.

positional arguments:
dir1                    Dir 1/left directory
dir2                    Dir 2/right directory

Mutual exclusive options (One must be given):
-d, --dir               Outputs the diff as a directory structure.
-a, --archive {xz,gz,bz2,zip,tar}
                        Outputs the diff as archive of given type.
-r, --report {console,file,both}
                        Outputs the diff as comparison report to given target.

Options:
-o, --outpath OUTPATH   Output path name for the diff result. Defaults to the parent dir
                        of <dir2> if not given.
-i, --indepth           Compares the files content instead statinfos like size, date of
                        last change.
-n, --no_log            Deactivates the use of a logfile in the script path.
-l, --loglevel          Set minimum log-level for the console. Default is `notable`. Use
                        `warning` or higher to reduce output.         
--version               show program\'s version number and exit
-h, --help              show this help message and exit
```


### Example CLI usage
Compares the two given dirs and places the difference to the default ouput directory.
`python3 diff2patch.py -d /home/user/example/dir_v0.1 /home/user/example/dir_v0.2`

Compares two dirs, copies the difference to a dir und constructs a gzip archive from
it. This is then placed in the given output path.
`python3 diff2patch.py -a gz ~/example/dir_v0.1 ~/example/dir_v0.2 -o ~/outdir`

Compares and prints the found difference to the console window.
`python3 diff2patch.py -r console /some/path/dir_1 /some/path/dir_2`

<!-- ### Motivation -->

## Legal
### License

__Diff2patch__ is licensed under Apache-2.0. See the [LICENSE](LICENSE) file for more
details.