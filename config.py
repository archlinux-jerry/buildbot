#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#### config for all

ARCHS = ['aarch64', 'any', 'armv7h', 'x86_64']
REPO_NAME='jerryxiao'
PKG_COMPRESSION='xz'
BUILD_ARCHS = ['aarch64', 'x86_64']
BUILD_ARCH_MAPPING = {'aarch64': 'aarch64', 'x86_64': 'x86_64', 'any': 'x86_64', 'armv7h': None}

AUTOBUILD_FNAME = 'autobuild.yaml'


#### config for repo.py

REPO_CMD = 'repo-add --verify --remove'
REPO_REMOVE_CMD = 'repo-remove --verify'
RECENT_VERSIONS_KEPT = 3
PREFERRED_ANY_BUILD_ARCH = 'x86_64'


#### config for repod.py

REPOD_BIND_ADDRESS = ('localhost', 7010)
REPOD_BIND_PASSWD = b'mypassword'

REPO_PUSH_BANDWIDTH = 1 # 1Mbps
GPG_VERIFY_CMD = 'gpg --verify'


#### config for package.py

# Archlinux-Jerry Build Bot <buildbot@mail.jerryxiao.cc>
GPG_KEY = 'BEE4F1D5A661CA1FEA65C38093962CE07A0D5B7D'
GPG_SIGN_CMD = (f'gpg --default-key {GPG_KEY} --no-armor '
                 '--pinentry-mode loopback --passphrase \'\' '
                 '--detach-sign --yes --')

#### config for buildbot.py

UPDATE_INTERVAL = 60 # mins
MASTER_BIND_ADDRESS = ('localhost', 7011)
MASTER_BIND_PASSWD = b'mypassword'
PKGBUILD_DIR = 'pkgbuilds'
MAKEPKG = 'makepkg --nosign --needed --noconfirm --noprogressbar --nocolor'

MAKEPKG_UPD_CMD = 'makepkg --syncdeps --nobuild'
MAKEPKG_MAKE_CMD = 'makepkg --syncdeps --noextract'
MAKEPKG_MAKE_CMD_CLEAN = 'makepkg --syncdeps --noextract --clean --cleanbuild'
MAKEPKG_MAKE_CMD_MARCH = 'makepkg --syncdeps --clean --cleanbuild'

MAKEPKG_PKGLIST_CMD = f'{MAKEPKG} --packagelist'

CONTAINER_BUILDBOT_ROOT = 'shared/buildbot'
SHELL_ARCH_X64 = ['/usr/bin/sudo', 'machinectl', '--quiet', 'shell', 'build@archlinux', '/bin/bash', '-x', '-e', '-c']
SHELL_ARCH_ARM64 = ['/usr/bin/sudo', 'machinectl', '--quiet', 'shell', 'root@alarm', '/bin/su', '-l', 'alarm', '-c']
SHELL_ARM64_ADDITIONAL = 'set -e; set -x'
SHELL_TRAP = 'trap \'echo ++ exit $?\' ERR EXIT'

UPLOAD_CMD = 'rsync -avPh \"{src}\" repoupload:/srv/repo/buildbot/repo/updates/'

GIT_PULL = 'git pull'
GIT_RESET_SUBDIR = 'git checkout HEAD -- .'
