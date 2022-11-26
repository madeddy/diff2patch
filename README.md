# diff2patch
A python tool to compare two directorys and compose a list with all found differences.
These can then
- viewed in the terminal as report,
- written to a text-file as report or 
- used to compose a patch with all different files.
Said patch content can be written as simple directory or archive.

## Dependencys
- python 3.10 or newer
### Optional
- python module _colorama_ for terminal colors in some windows OS
Colors just a fancfull addition and it works without it. Some people might want it. There
are also other ways like _ansicon_ or the use of Windows terminal, where ANSI already
integrated is. (code changes needed)

## Usage
### Command line parameter overview
```sh
diff2patch.py [-h] (-d | -a {xz,gz,bz2,zip,tar} | -r {console,file,both}) [-o OUTPATH]
[-i] [--version] old new

Generates a diff patch or overview of two given directory structures.

positional arguments:
old                   Old/left directory
new                   New/right directory

options:
-h, --help            show this help message and exit
-d, --dir             Outputs the diff as a directory structure.
-a {xz,gz,bz2,zip,tar}, --archive {xz,gz,bz2,zip,tar}
                      Outputs the diff as archive of given type.
-r {console,file,both}, --report {console,file,both}
                      Outputs the diff as comparison report to given target.
-o OUTPATH, --outpath OUTPATH
                      Output path name for the diff result. Defaults to the parent dir
                      of <new> if not given.
-i, --indepth         Compares the files content instead stats like size, date of last
                      change.
--version             show program's version number and exit
```

### Example CLI usage
Compares the two given dirs and places the difference to the default ouput directory.
`python3.10 diff2patch.py -d /home/user/example/dir_v0.1 /home/user/example/dir_v0.2`

Compares two dirs, copies the difference to a dir und constructs a gzip archive from
it. This is then placed in the given output path.
`python3.10 diff2patch.py -a gz ~/example/dir_v0.1 ~/example/dir_v0.2 -o ~/outdir`

Compares and prints the found difference to the console window.
`python3.10 diff2patch.py -r console /some/path/dir_1 /some/path/dir_2`

<!-- ### Motivation -->

## Legal
### License

__Diff2patch__ is licensed under Apache-2.0. See the [LICENSE](LICENSE) file for more
details.