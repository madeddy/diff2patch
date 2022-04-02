# diff2patch
A tool to compare two directorys and compose a list with all found differences. These can
then be shown in the terminal/text-file as report or used to compose a patch
directory/archive with all different files.

## Usage
### Command line parameter overview
```
diff2patch.py (-d | -a {xz,gz,bz2,zip,tar} | -r {console,file,both})
[-o OUTPATH] [-i] [--verbose level [0-2]] [--version] [-h]
old_dir new_dir

positional arguments:
old                    Old/left directory
new                    New/right directory

options:
-d, --dir              Outputs the diff to a directory.
-a, --archive {xz,gz,bz2,zip,tar} Outputs the diff as archive of given type.
-r, --report {console,file,both}  Outputs the diff as comparison report to given
                       target.
-o, --outpath OUTPATH  Output path for the differing files, dirs. Defaults to the
                       parent of <new>
-i, --indepth          Compares the files content instead just their stats.
--verbose level [0-2]  Amount of info output. 0:none, 2:much, default:1
--version              show program's version number and exit
-h, --help             show this help message and exit
```

### Example CLI usage
Compares the two given dirs and copies the difference to standard ouput dir.
`python3.10 diff2patch.py /home/user/example/dir_v0.1 /home/user/example/dir_v0.2 -d`

Compares and prints the found difference to the console window.
`python3.10 diff2patch.py /some/path/dir_1 /some/path/dir_2 -r console`

<!-- ### Motivation -->

## Legal
### License

__Diff2patch__ is licensed under Apache-2.0. See the [LICENSE](LICENSE) file for more details.