#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# client.py: Automatic management tool for an arch repo.
# This file is part of Buildbot by JerryXiao

import logging
import os
from multiprocessing.connection import Client
from time import sleep

from config import REPOD_BIND_ADDRESS, REPOD_BIND_PASSWD, \
                   MASTER_BIND_ADDRESS, MASTER_BIND_PASSWD, \
                   CONSOLE_LOGFILE, MAIN_LOGFILE

from utils import print_exc_plus

logger = logging.getLogger(f'buildbot.{__name__}')

abspath=os.path.abspath(__file__)
abspath=os.path.dirname(abspath)
os.chdir(abspath)

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
    def print_log(debug=False):
        if debug:
            os.system(f'tail -n 43 -f \"{MAIN_LOGFILE}\"')
        else:
            os.system(f'tail -n 43 -f \"{CONSOLE_LOGFILE}\"')
    try:
        actions = {
                    'info':     'show buildbot info',
                    'update':   '[--overwrite] update pushed files to the repo',
                    'clean':    '[dir / all] checkout pkgbuilds in packages',
                    'rebuild':  '[dir1 dir2 --clean] rebuild packages',
                    'log':      '[--debug] print log',
                    'upload':   '[dir1 dir2 --overwrite] force upload packages',
                    'getup':    'check for updates now'
                  }
        parser = argparse.ArgumentParser(description='Client for buildbot',
                                        formatter_class=argparse.RawTextHelpFormatter)
        __action_help = "\n".join([f"{a}:\t{actions[a]}" for a in actions])
        parser.add_argument('action', nargs='*', help=f'Choose which action to invoke:\n\n{__action_help}')
        parser.add_argument('--overwrite', nargs='?', default='False', help='overwrite existing files')
        parser.add_argument('--debug', nargs='?', default='False', help='print debug logs')
        parser.add_argument('--clean', nargs='?', default='True', help='clean build packages')
        args = parser.parse_args()
        action = args.action
        for switch in ('overwrite', 'debug', 'clean'):
            s = getattr(args, switch)
            if str(s).lower() in ('false', 'no', 'n', '0'):
                setattr(args, switch, False)
            else:
                setattr(args, switch, True)
        if not (action and len(action) >= 1 and action[0] in actions):
            parser.print_help()
            parser.exit(status=1)
        if action[0] == 'info':
            server=(MASTER_BIND_ADDRESS, MASTER_BIND_PASSWD)
            logger.info(run('info', server=server))
        elif action[0] == 'getup':
            server=(MASTER_BIND_ADDRESS, MASTER_BIND_PASSWD)
            logger.info(run('getup', server=server))
        elif action[0] == 'update':
            server=(REPOD_BIND_ADDRESS, REPOD_BIND_PASSWD)
            logger.info(run('update', kwargs={'overwrite': args.overwrite}, server=server))
        elif action[0] == 'clean':
            if len(action) <= 1:
                print('Error: Need package name')
                parser.print_help()
                parser.exit(status=1)
            server=(MASTER_BIND_ADDRESS, MASTER_BIND_PASSWD)
            if 'all' in action[1:]:
                logger.info(run('clean_all', server=server))
            else:
                for p in action[1:]:
                    logger.info(run('clean', args=(p,), server=server))
        elif action[0] == 'rebuild':
            if len(action) <= 1:
                print('Error: Need package name')
                parser.print_help()
                parser.exit(status=1)
            server=(MASTER_BIND_ADDRESS, MASTER_BIND_PASSWD)
            for p in action[1:]:
                logger.info(run('rebuild_package', args=(p,), kwargs={'clean': args.clean}, server=server))
        elif action[0] == 'upload':
            if len(action) <= 1:
                print('Error: Need package name')
                parser.print_help()
                parser.exit(status=1)
            server=(MASTER_BIND_ADDRESS, MASTER_BIND_PASSWD)
            for p in action[1:]:
                logger.info(run('force_upload', args=(p,), kwargs={'overwrite': args.overwrite}, server=server))
        elif action[0] == 'log':
            logger.info('printing logs')
            print_log(debug=args.debug)
        else:
            parser.error("Please choose an action")
    except Exception:
        print_exc_plus()
        parser.exit(status=1)
