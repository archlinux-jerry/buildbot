#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# buildbot.py: Automatic management tool for an arch repo.
# This file is part of Buildbot by JerryXiao

import logging
from multiprocessing.connection import Listener
from time import time, sleep
import os
from pathlib import Path
from subprocess import CalledProcessError

from utils import print_exc_plus, background

from config import ARCHS, BUILD_ARCHS, BUILD_ARCH_MAPPING, \
                   MASTER_BIND_ADDRESS, MASTER_BIND_PASSWD, \
                   PKGBUILD_DIR, MAKEPKG_PKGLIST_CMD, MAKEPKG_UPD_CMD
from utils import bash, get_pkg_details_from_name, vercmp

import json

from yamlparse import load_all as load_all_yaml

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

abspath=os.path.abspath(__file__)
abspath=os.path.dirname(abspath)
os.chdir(abspath)

REPO_ROOT = Path(PKGBUILD_DIR)

class Job:
    def __init__(self, arch, pkgdir, packagelist, version):
        buildarch = BUILD_ARCH_MAPPING.get(arch, None)
        assert buildarch in BUILD_ARCHS
        self.arch = arch
        self.buildarch = buildarch
        self.pkgdir = pkgdir
        self.packagelist = packagelist
        self.version = version
        self.added = time()
        self.claimed = 0

class jobsManager:
    def __init__(self):
        self.__buildjobs = dict()
        for arch in BUILD_ARCHS:
            self.__buildjobs.setdefault(arch, list())
        self.__uploadjobs = list()
        self.__curr_job = None
        self.pkgconfigs = load_all_yaml()
    def _new_buildjob(self, job, buildarch):
        assert type(job) is Job
        self.__buildjobs.get(buildarch).append(job)
    def claim_job(self, buildarch):
        assert buildarch in BUILD_ARCHS
        if self.__curr_job:
            return None
        jobs = self.__buildjobs.get(buildarch, list())
        if jobs:
            self.__curr_job = jobs.pop(0)
            return self.__curr_job
    def __finish_job(self, pkgdir):
        assert pkgdir == self.__curr_job.pkgdir
        # do upload
        self.__curr_job = None
        return True
    def tick(self):
        '''
            check for updates,
            create new jobs
            and run them
        '''
        if self.__curr_job is None:
            updates = updmgr.check_update()
            for update in updates:
                (pkg, packagelist, ver) = update


jobsmgr = jobsManager()

class updateManager:
    def __init__(self, filename='pkgver.json'):
        self.__filename = filename
        self.__pkgvers = dict()
        self.__load()
    def __load(self):
        if Path(self.__filename).exists():
            with open(self.__filename,"r") as f:
                try:
                    pkgvers = json.loads(f.read())
                except json.JSONDecodeError:
                    logger.error('pkgver.json - Bad json')
                    print_exc_plus
                    exit(1)
        else:
            logger.warning(f'No {self.__filename} found')
            pkgvers = dict()
        assert type(pkgvers) is dict
        for pkgname in pkgvers:
            assert type(pkgname) is str
        self.__pkgvers = pkgvers
    def _save(self):
        pkgvers = json.dumps(self.__pkgvers, indent=4)
        pkgvers += '\n'
        with open(self.__filename,"w") as f:
            if f.writable:
                f.write(pkgvers)
            else:
                logger.error('pkgver.json - Not writable')
    def __get_package_list(self, dirname):
        pkgdir = REPO_ROOT / dirname
        assert pkgdir.exists()
        pkglist = bash(MAKEPKG_PKGLIST_CMD, cwd=pkgdir)
        pkglist = pkglist.split('\n')
        return pkglist
    def __get_new_ver(self, dirname):
        pkgfiles = self.__get_package_list(dirname)
        ver = get_pkg_details_from_name(pkgfiles[0])
        return (ver, pkgfiles)
    def check_update(self):
        updates = list()
        for pkg in jobsmgr.pkgconfigs:
            pkgdir = REPO_ROOT / pkg.dirname
            logger.info(f'checking update: {pkg.dirname}')
            bash(MAKEPKG_UPD_CMD, cwd=pkgdir, RUN_CMD_TIMEOUT=60*60)
            if pkg.type in ('git', 'manual'):
                (ver, pkgfiles) = self.__get_new_ver(pkg.dirname)
                oldver = self.__pkgvers.get(pkg.dirname, None)
                if oldver is None or vercmp(ver, oldver) == 1:
                    self.__pkgvers[pkg.dirname] = ver
                    updates.append((pkg, pkgfiles, ver))
                else:
                    logger.warning(f'package: {pkg.dirname} downgrade attempted')
            else:
                logger.warning(f'unknown package type: {pkg.type}')
        self._save()
        return updates

updmgr = updateManager()


@background
def __main():
    pass







def run(funcname, args=list(), kwargs=dict()):
    if funcname in ('clean', 'regenerate', 'remove',
                    'update', 'push_files', 'add_files'):
        logger.info('running: %s %s %s',funcname, args, kwargs)
        ret = eval(funcname)(*args, **kwargs)
        logger.info('done: %s %s',funcname, ret)
        return ret
    else:
        logger.error('unexpected: %s %s %s',funcname, args, kwargs)
        return False


if __name__ == '__main__':
    __main() # start the main worker thread
    while True:
        try:
            with Listener(MASTER_BIND_ADDRESS, authkey=MASTER_BIND_PASSWD) as listener:
                with listener.accept() as conn:
                    logger.info('connection accepted from %s', listener.last_accepted)
                    myrecv = conn.recv()
                    if type(myrecv) is list and len(myrecv) == 3:
                        (funcname, args, kwargs) = myrecv
                        funcname = str(funcname)
                        conn.send(run(funcname, args=args, kwargs=kwargs))
        except Exception:
            print_exc_plus()
        except KeyboardInterrupt:
            logger.info('KeyboardInterrupt')
            print_exc_plus()
            break
