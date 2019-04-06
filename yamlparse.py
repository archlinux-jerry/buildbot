#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import logging
from yaml import load, Loader
from pathlib import Path

from utils import print_exc_plus

from config import PKGBUILD_DIR, AUTOBUILD_FNAME

logger = logging.getLogger(__name__)

abspath=os.path.abspath(__file__)
abspath=os.path.dirname(abspath)
os.chdir(abspath)

# parse all autobuild.yaml files

REPO_ROOT = Path(PKGBUILD_DIR)

class pkgConfig:
    def __init__(self, dirname, pkgtype, cleanbuild, timeout, extra):
        self.dirname = dirname

        self.type = pkgtype
        self.__determine_type()

        if cleanbuild is None:
            cleanbuild = True
        assert type(cleanbuild) is bool
        self.cleanbuild = cleanbuild

        self.timeout = 30 if timeout is None else int(timeout)
        # timeout in minutes

        self.__extra = extra
        self.__process_extra()

    def __determine_type(self):
        if self.type in (None, 'auto'):
            if self.dirname.endswith('-git'):
                self.type = 'git'
                return
        self.type = 'manual'

    def __process_extra(self):
        stages = ('prebuild', 'postbuild', 'update', 'failure')
        for stage in stages:
            setattr(self, stage, list())
        for entry in self.__extra:
            assert type(entry) is dict and len(entry) == 1
            for k in entry:
                if k in stages:
                    cmd = entry.get(k, list())
                    assert type(cmd) is list
                    setattr(self, k, cmd)

    def __repr__(self):
        ret = "pkgConfig("
        for myproperty in \
            (
                'dirname', 'type', 'cleanbuild', 'timeout'
                'prebuild', 'postbuild', 'update', 'failure'
            ):
            ret += f'{myproperty}={getattr(self, myproperty)},'
        ret += ')'
        return ret

def load_all():
    pkgconfigs = list()
    for mydir in REPO_ROOT.iterdir():
        try:
            if mydir.is_dir() and (mydir / AUTOBUILD_FNAME).exists():
                # parsing yaml
                logger.info('Bulidbot: found %s in %s', AUTOBUILD_FNAME,
                                                        mydir / AUTOBUILD_FNAME)
                with open(mydir / AUTOBUILD_FNAME, 'r') as f:
                    content = f.read()
                    content = load(content, Loader=Loader)
                    assert type(content) is dict
                    args = [content.get(part, None) for part in \
                            ('type', 'cleanbuild', 'timeout', 'extra')]
                    args = [mydir.name] + args
                    pkgconfigs.append(pkgConfig(*args))
        except Exception:
            logger.error(f'Error while parsing {AUTOBUILD_FNAME} for {mydir.name}')
            print_exc_plus()
    return pkgconfigs

if __name__ == '__main__':
    print(load_all())
