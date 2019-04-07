# Buildbot

## Typical autobuild.yaml format
```
type:
    auto (by package name)
    git (this is a git package and will check source for updates)
    manual (this package will only be updated when new release is pushed)
cleanbuild:
    true / false
timeout:
    30 (30 mins, int only)
extra: (wip)
    - update:
        - /bin/true
    - prebuild:
        - echo "Hello World!"
    - postbuild:
        - ls > list
    - failure:
        - rm file
```
