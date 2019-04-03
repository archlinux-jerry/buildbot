# Buildbot

## Typical autobuild.yaml format
### Note
Anything starting with bash will be considered as bash commands.
`e.g. - bash ls -al`  
All of the four blocks: updates, prebuild, build, postbuild can be ommited, and their first value will be used.
### Example
```
updates:
    - repo (repo only, it means the package will only be built when a new commit is pushed to repo.)
    - git <url> <remote/branch>* (* means optional)
    - ?? (tbd)
prebuild:
    - standard (do nothing)
    - ??
build:
    - standard (makepkg -s, note that missing aur dependencies will not be resolved.)
    - ??
postbuild:
    - standard (sign and upload)
    - do_nothing (leave it alone)
    - ??
```