#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# repod.py: Automatic management tool for an arch repo.
# This file is part of Buildbot by JerryXiao

import logging
from multiprocessing.connection import Client
from time import sleep

from config import REPOD_BIND_ADDRESS, REPOD_BIND_PASSWD, \
                   MASTER_BIND_ADDRESS, MASTER_BIND_PASSWD

from utils import print_exc_plus

logger = logging.getLogger(f'buildbot.{__name__}')

def run(funcname, args=list(), kwargs=dict(), retries=0, server=(REPOD_BIND_ADDRESS, REPOD_BIND_PASSWD)):
    try:
        logger.info('client: %s %s %s',funcname, args, kwargs)
        (addr, authkey) = server
        with Client(addr, authkey=authkey) as conn:
            conn.send([funcname, args, kwargs])
            return conn.recv()
    except ConnectionRefusedError:
        if retries <= 10:
            logger.info("Server refused, retry after 60s")
            sleep(60)
            return run(funcname, args=args, kwargs=kwargs, retries=retries+1)
        else:
            logger.error("Server refused")
            return False
    except EOFError:
        logger.error('Internal server error')
        return False
    except Exception:
        print_exc_plus()

if __name__ == '__main__':
    import argparse
    from utils import configure_logger
    configure_logger(logger)
    try:
        parser = argparse.ArgumentParser(description='Client for buildbot')
        parser.add_argument('--info', action='store_true', help='show buildbot info')
        parser.add_argument('--update', action='store_true', help='update pushed files to the repo')
        parser.add_argument('--cleanall', action='store_true', help='checkout pkgbuilds')
        parser.add_argument('--clean', nargs='?', default=None, help='checkout pkgbuilds in one package')
        parser.add_argument('--rebuild', nargs='?', default=None, help='rebuild a package with its dirname')
        args = parser.parse_args()
        if args.info:
            server=(MASTER_BIND_ADDRESS, MASTER_BIND_PASSWD)
            logger.info(run('info', server=server))
        elif args.update:
            server=(REPOD_BIND_ADDRESS, REPOD_BIND_PASSWD)
            logger.info(run('update', kwargs={'overwrite': False}, server=server))
        elif args.cleanall:
            server=(MASTER_BIND_ADDRESS, MASTER_BIND_PASSWD)
            logger.info(run('clean_all', server=server))
        elif args.clean:
            server=(MASTER_BIND_ADDRESS, MASTER_BIND_PASSWD)
            logger.info(run('clean', args=(args.clean,), server=server))
        elif args.rebuild:
            server=(MASTER_BIND_ADDRESS, MASTER_BIND_PASSWD)
            logger.info(run('rebuild_package', args=(args.rebuild,), kwargs={'clean': True}, server=server))
        else:
            parser.error("Please choose an action")
    except Exception:
        print_exc_plus()
        parser.exit(status=1)
