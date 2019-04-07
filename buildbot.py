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

from config import ARCHS, BUILD_ARCHS, BUILD_ARCH_MAPPING, \
                   MASTER_BIND_ADDRESS, MASTER_BIND_PASSWD, \
                   PKGBUILD_DIR, MAKEPKG_PKGLIST_CMD, MAKEPKG_UPD_CMD, \
                   MAKEPKG_MAKE_CMD, MAKEPKG_MAKE_CMD_CLEAN

from utils import print_exc_plus, background, \
                  bash, get_pkg_details_from_name, vercmp, \
                  nspawn_shell, mon_nspawn_shell, get_arch_from_pkgbuild

import json

from yamlparse import load_all as load_all_yaml

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

abspath=os.path.abspath(__file__)
abspath=os.path.dirname(abspath)
os.chdir(abspath)

REPO_ROOT = Path(PKGBUILD_DIR)

class Job:
    def __init__(self, buildarch, pkgconfig, version, multiarch=False):
        assert buildarch in BUILD_ARCHS
        self.arch = buildarch
        self.pkgconfig = pkgconfig
        self.version = version
        self.multiarch = multiarch
        self.added = time()

class jobsManager:
    def __init__(self):
        self.__buildjobs = list()
        self.__uploadjobs = list()
        self.__curr_job = None
        self.pkgconfigs = load_all_yaml()
    def _new_buildjob(self, job):
        assert type(job) is Job
        job_to_remove = list()
        for previous_job in self.__buildjobs:
            if job.pkgconfig.dirname == previous_job.pkgconfig.dirname and \
               job.arch == previous_job.arch:
                job_to_remove.append(previous_job)
        for oldjob in job_to_remove:
            self.__buildjobs.remove(oldjob)
            logger.info('removed an old job for %s %s, %s => %s',
                        job.pkgconfig.dirname, job.arch,
                        oldjob.version, job.version)
        logger.info('new job for %s %s %s',
                     job.pkgconfig.dirname, job.arch, job.version)
        self.__buildjobs.append(job)
    def __get_job(self):
        if self.__curr_job:
            return None
        jobs = self.__buildjobs
        if jobs:
            self.__curr_job = jobs.pop(0)
            return self.__curr_job
    def __finish_job(self, pkgdir):
        assert pkgdir == self.__curr_job.pkgconfig.dirname
        # do upload
        self.__curr_job = None
        return True
    def __makepkg(self, job):
        mkcmd = MAKEPKG_MAKE_CMD_CLEAN if job.pkgconfig.cleanbuild \
                                       else MAKEPKG_MAKE_CMD
        cwd = REPO_ROOT / job.pkgconfig.dirname
        logger.info('makepkg in %s %s', job.pkgconfig.dirname, job.arch)
        return mon_nspawn_shell(arch=job.arch, cwd=cwd, cmdline=mkcmd,
                                logfile = cwd / 'buildbot.log.update',
                                short_return = True)
    def __clean(self, job):
        cwd = REPO_ROOT / job.pkgconfig.dirname
        logger.info('cleaning build dir for %s %s',
                    job.pkgconfig.dirname, job.arch)
        nspawn_shell(job.arch, 'rm -rf src pkg', cwd=cwd)
    def __sign(self, job):
        '''
            wip
        '''
        cwd = REPO_ROOT / job.pkgconfig.dirname
        print(nspawn_shell(job.arch, 'ls -l', cwd=cwd))
        #nspawn_shell(job.arch, 'rm -rf src pkg', cwd=cwd)
    def __upload(self, job):
        '''
            wip
        '''
        cwd = REPO_ROOT / job.pkgconfig.dirname
        print(nspawn_shell(job.arch, 'ls -l', cwd=cwd))
        #nspawn_shell(job.arch, 'rm -rf src pkg', cwd=cwd)
    def tick(self):
        '''
            check for updates,
            create new jobs
            and run them
        '''
        if not self.__buildjobs:
            # This part check for updates
            updates = updmgr.check_update()
            for update in updates:
                (pkgconfig, ver, buildarchs) = update
                march = True if len(buildarchs) >= 2 else False
                for arch in buildarchs:
                    newjob = Job(arch, pkgconfig, ver, multiarch=march)
                    self._new_buildjob(newjob)
        else:
            # This part does the job
            for job in self.__buildjobs:
                cwd = REPO_ROOT / job.pkgconfig.dirname
                if job.multiarch:
                    # wip
                    pass
                else:
                    self.__makepkg(job)
                    self.__sign(job)
                    self.__upload(job)
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
    def __get_package_list(self, dirname, arch):
        pkgdir = REPO_ROOT / dirname
        assert pkgdir.exists()
        pkglist = nspawn_shell(arch, MAKEPKG_PKGLIST_CMD, cwd=pkgdir)
        pkglist = pkglist.split('\n')
        return pkglist
    def __get_new_ver(self, dirname, arch):
        pkgfiles = self.__get_package_list(dirname, arch)
        ver = get_pkg_details_from_name(pkgfiles[0]).ver
        return ver
    def check_update(self):
        updates = list()
        for pkg in jobsmgr.pkgconfigs:
            pkgdir = REPO_ROOT / pkg.dirname
            logger.info(f'checking update: {pkg.dirname}')
            pkgbuild = pkgdir / 'PKGBUILD'
            archs = get_arch_from_pkgbuild(pkgbuild)
            buildarchs = [BUILD_ARCH_MAPPING.get(arch, None) for arch in archs]
            buildarchs = [arch for arch in buildarchs if arch is not None]
            # hopefully we only need to check one arch for update
            arch = 'x86_64' if 'x86_64' in buildarchs else buildarchs[0] # prefer x86
            mon_nspawn_shell(arch, MAKEPKG_UPD_CMD, cwd=pkgdir, minutes=60,
                             logfile = pkgdir / 'buildbot.log.update',
                             short_return = True)
            if pkg.type in ('git', 'manual'):
                ver = self.__get_new_ver(pkg.dirname, arch)
                oldver = self.__pkgvers.get(pkg.dirname, None)
                if oldver is None or vercmp(ver, oldver) == 1:
                    self.__pkgvers[pkg.dirname] = ver
                    updates.append((pkg, ver, buildarchs))
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
                        logger.info('running: %s %s %s', funcname, args, kwargs)
                        conn.send(run(funcname, args=args, kwargs=kwargs))
        except Exception:
            print_exc_plus()
        except KeyboardInterrupt:
            logger.info('KeyboardInterrupt')
            print_exc_plus()
            break
