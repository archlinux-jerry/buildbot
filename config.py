#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#### config for all

ARCHS = ['aarch64', 'any', 'armv7h', 'x86_64']
REPO_NAME='jerryxiao'
PKG_COMPRESSION='xz'
BUILD_ARCHS = ['aarch64', 'any', 'x86_64']

#### config for repo.py
REPO_CMD = 'repo-add --verify --remove'
REPO_REMOVE_CMD = 'repo-remove --verify'
RECENT_VERSIONS_KEPT = 3
PREFERRED_ANY_BUILD_ARCH = 'x86_64'

#### config for package.py
# Archlinux-Jerry Build Bot <buildbot@mail.jerryxiao.cc>
GPG_KEY = 'BEE4F1D5A661CA1FEA65C38093962CE07A0D5B7D'
GPG_SIGN_CMD = (f'gpg --default-key {GPG_KEY} --no-armor'
                 '--pinentry-mode loopback --passphrase \'\''
                 '--detach-sign --yes -- ')

