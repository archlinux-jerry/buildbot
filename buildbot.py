#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# buildbot.py: Automatic management tool for an arch repo.
# This file is part of Buildbot by JerryXiao

import logging
from multiprocessing.connection import Listener
from time import time, sleep
import os
from pathlib import Path
from shutil import rmtree
from subprocess import CalledProcessError

from shared_vars import PKG_SUFFIX, PKG_SIG_SUFFIX

from config import ARCHS, BUILD_ARCHS, BUILD_ARCH_MAPPING, \
                   MASTER_BIND_ADDRESS, MASTER_BIND_PASSWD, \
                   PKGBUILD_DIR, MAKEPKG_PKGLIST_CMD, MAKEPKG_UPD_CMD, \
                   MAKEPKG_MAKE_CMD, MAKEPKG_MAKE_CMD_CLEAN, \
                   GPG_SIGN_CMD, GPG_VERIFY_CMD, UPDATE_INTERVAL, \
                   MAKEPKG_MAKE_CMD_MARCH, UPLOAD_CMD

from utils import print_exc_plus, background, \
                  bash, get_pkg_details_from_name, vercmp, \
                  nspawn_shell, mon_nspawn_shell, get_arch_from_pkgbuild, \
                  configure_logger, mon_bash

from client import run as rrun

import json

from yamlparse import load_all as load_all_yaml

abspath=os.path.abspath(__file__)
abspath=os.path.dirname(abspath)
os.chdir(abspath)

logger = logging.getLogger('buildbot')
configure_logger(logger, logfile='buildbot.log', rotate_size=1024*1024*10)

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
        self.pkgconfigs = None
        self.last_updatecheck = 0.0
        self.idle = False
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
        cwd = REPO_ROOT / job.pkgconfig.dirname
        if job.multiarch:
            # assume a clean env, no source avail
            mkcmd = MAKEPKG_MAKE_CMD_MARCH
        else:
            mkcmd = MAKEPKG_MAKE_CMD_CLEAN if job.pkgconfig.cleanbuild \
                                        else MAKEPKG_MAKE_CMD
        logger.info('makepkg in %s %s', job.pkgconfig.dirname, job.arch)
        return mon_nspawn_shell(arch=job.arch, cwd=cwd, cmdline=mkcmd,
                                logfile = cwd / 'buildbot.log.makepkg',
                                short_return = True,
                                seconds=job.pkgconfig.timeout*60)
    def __clean(self, job, remove_pkg=False, rm_src=True):
        cwd = REPO_ROOT / job.pkgconfig.dirname
        logger.info('cleaning build dir for %s, %sremoving pkg',
                    job.pkgconfig.dirname, '' if remove_pkg else 'not ')
        for fpath in [f for f in cwd.iterdir()]:
            if rm_src and fpath.is_dir() and \
                          fpath.name in ('pkg', 'src'):
                rmtree(fpath)
            elif remove_pkg and fpath.is_file() and \
                 ((not job.multiarch) or job.arch in fpath.name) and \
                 (fpath.name.endswith(PKG_SUFFIX) or \
                  fpath.name.endswith(PKG_SIG_SUFFIX)):
                fpath.unlink()
    def __sign(self, job):
        cwd = REPO_ROOT / job.pkgconfig.dirname
        for fpath in cwd.iterdir():
            if fpath.name.endswith(PKG_SUFFIX):
                bash(f'{GPG_SIGN_CMD} {fpath.name}', cwd=cwd)
    def __upload(self, job):
        '''
            wip
        '''
        suc = True
        cwd = REPO_ROOT / job.pkgconfig.dirname
        f_to_upload = list()
        for fpath in cwd.iterdir():
            if fpath.name.endswith(PKG_SUFFIX) and \
               get_pkg_details_from_name(fpath.name).ver == job.version:
                sigpath = fpath.parent / f'{fpath.name}.sig'
                assert sigpath.exists()
                f_to_upload.append(sigpath)
                f_to_upload.append(fpath)
        for f in f_to_upload:
            size = f.stat().st_size / 1000 / 1000
            if f.name.endswith(PKG_SUFFIX):
                for _ in range(10):
                    timeout = rrun('push_start', args=(f.name, size))
                    if timeout > 0:
                        break
                    else:
                        logger.warning('Remote is busy (-1), wait 1 min x10')
                        sleep(60)
            else:
                timeout = 60
            logger.info(f'Uploading {f}, timeout in {timeout}s')
            mon_bash(UPLOAD_CMD.format(src=f), seconds=timeout)
            if f.name.endswith(PKG_SUFFIX):
                logger.info(f'Requesting repo update for {f.name}')
                res = rrun('push_done', args=(f.name,), kwargs={'overwrite': False,})
                if res is None:
                    logger.info(f'Update success for {f.name}')
                else:
                    logger.error(f'Update failed for {f.name}, reason: {res}')
                    suc = False
        return suc
    def tick(self):
        '''
            check for updates,
            create new jobs
            and run them
        '''
        if not self.__buildjobs:
            # This part check for updates
            if time() - self.last_updatecheck <= UPDATE_INTERVAL * 60:
                if not self.idle:
                    logger.info('Buildbot is idling for package updates.')
                self.idle = True
                sleep(60)
                return
            self.last_updatecheck = time()
            self.idle = False
            self.pkgconfigs = load_all_yaml()
            updates = updmgr.check_update()
            for update in updates:
                (pkgconfig, ver, buildarchs) = update
                march = True if len(buildarchs) >= 2 else False
                for arch in buildarchs:
                    newjob = Job(arch, pkgconfig, ver, multiarch=march)
                    self._new_buildjob(newjob)
        else:
            # This part does the job
            job = self.__get_job()
            if job.multiarch:
                self.__clean(job, remove_pkg=True)
                self.__makepkg(job)
                self.__sign(job)
                if self.__upload(job):
                    self.__clean(job, remove_pkg=True)
            else:
                self.__makepkg(job)
                self.__sign(job)
                if self.__upload(job):
                    if job.pkgconfig.cleanbuild:
                        self.__clean(job, remove_pkg=True)
                    else:
                        self.__clean(job, rm_src=False, remove_pkg=True)
            self.__finish_job(job.pkgconfig.dirname)
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
        pkglist = [line for line in pkglist if not line.startswith('+')]
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
            mon_nspawn_shell(arch, MAKEPKG_UPD_CMD, cwd=pkgdir, seconds=60*60,
                             logfile = pkgdir / 'buildbot.log.update',
                             short_return = True)
            if pkg.type in ('git', 'manual'):
                ver = self.__get_new_ver(pkg.dirname, arch)
                oldver = self.__pkgvers.get(pkg.dirname, None)
                has_update = False
                if oldver:
                    res = vercmp(ver, oldver)
                    if res == 1:
                        has_update = True
                    elif res == -1:
                        logger.warning(f'package: {pkg.dirname} downgrade attempted')
                    elif res == 0:
                        logger.info(f'package: {pkg.dirname} is up to date')
                else:
                    has_update = True
                if has_update:
                    self.__pkgvers[pkg.dirname] = ver
                    updates.append((pkg, ver, buildarchs))
            else:
                logger.warning(f'unknown package type: {pkg.type}')
        self._save()
        return updates

updmgr = updateManager()




def info(*args, **kwargs):
    return (args, kwargs)

def run(funcname, args=list(), kwargs=dict()):
    if funcname in ('info',):
        logger.info('running: %s %s %s',funcname, args, kwargs)
        ret = eval(funcname)(*args, **kwargs)
        logger.info('done: %s %s',funcname, ret)
        return ret
    else:
        logger.error('unexpected: %s %s %s',funcname, args, kwargs)
        return False

@background
def __main():
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

if __name__ == '__main__':
    logger.info('Buildbot started.')
    __main() # start the Listener thread
    logger.info('Listener started.')
    while True:
        try:
            jobsmgr.tick()
        except Exception:
            print_exc_plus()
        except KeyboardInterrupt:
            logger.info('KeyboardInterrupt')
            print_exc_plus()
            break
        sleep(1)
