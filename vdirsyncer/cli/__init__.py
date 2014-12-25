# -*- coding: utf-8 -*-
'''
    vdirsyncer.cli
    ~~~~~~~~~~~~~~

    :copyright: (c) 2014 Markus Unterwaditzer & contributors
    :license: MIT, see LICENSE for more details.
'''

import functools
import os
import sys

from .tasks import sync_pair
from .utils import CliError, WorkerQueue, cli_logger, collections_for_pair, \
    handle_cli_error, load_config, parse_pairs_args
from .. import __version__, log
from ..doubleclick import click
from ..utils import expand_path


def catch_errors(f):
    @functools.wraps(f)
    def inner(*a, **kw):
        try:
            f(*a, **kw)
        except:
            if not handle_cli_error():
                sys.exit(1)

    return inner


def validate_verbosity(ctx, param, value):
    x = getattr(log.logging, value.upper(), None)
    if x is None:
        raise click.BadParameter('Invalid verbosity value {}. Must be '
                                 'CRITICAL, ERROR, WARNING, INFO or DEBUG'
                                 .format(value))
    return x


@click.group()
@click.option('--verbosity', '-v', default='INFO',
              callback=validate_verbosity,
              help='Either CRITICAL, ERROR, WARNING, INFO or DEBUG')
@click.version_option(version=__version__)
@click.pass_context
@catch_errors
def app(ctx, verbosity):
    '''
    vdirsyncer -- synchronize calendars and contacts
    '''
    log.add_handler(log.stdout_handler)
    log.set_level(verbosity)

    if ctx.obj is None:
        ctx.obj = {}

    if 'config' not in ctx.obj:
        fname = expand_path(os.environ.get('VDIRSYNCER_CONFIG',
                                           '~/.vdirsyncer/config'))
        if not os.path.exists(fname):
            xdg_config_dir = os.environ.get('XDG_CONFIG_HOME',
                                            expand_path('~/.config/'))
            fname = os.path.join(xdg_config_dir, 'vdirsyncer/config')
        try:
            with open(fname) as f:
                ctx.obj['config'] = load_config(f)
        except Exception as e:
            raise CliError('Error during reading config {}: {}'
                           .format(fname, e))

main = app

max_workers_option = click.option(
    '--max-workers', default=0, type=click.IntRange(min=0, max=None),
    help=('Use at most this many connections, 0 means unlimited.')
)


@app.command()
@click.argument('pairs', nargs=-1)
@click.option('--force-delete/--no-force-delete',
              help=('Disable data-loss protection for the given pairs. '
                    'Can be passed multiple times'))
@max_workers_option
@click.pass_context
@catch_errors
def sync(ctx, pairs, force_delete, max_workers):
    '''
    Synchronize the given collections or pairs. If no arguments are given,
    all will be synchronized.

    Examples:
    `vdirsyncer sync` will sync everything configured.
    `vdirsyncer sync bob frank` will sync the pairs "bob" and "frank".
    `vdirsyncer sync bob/first_collection` will sync "first_collection"
    from the pair "bob".
    '''
    general, all_pairs, all_storages = ctx.obj['config']

    cli_logger.debug('Using {} maximal workers.'.format(max_workers))
    wq = WorkerQueue(max_workers)
    wq.handled_jobs = set()

    for pair_name, collections in parse_pairs_args(pairs, all_pairs):
        wq.spawn_worker()
        wq.put(functools.partial(sync_pair, pair_name=pair_name,
                                 collections_to_sync=collections,
                                 general=general, all_pairs=all_pairs,
                                 all_storages=all_storages,
                                 force_delete=force_delete))

    wq.join()


@app.command()
@click.argument('pairs', nargs=-1)
@max_workers_option
@click.pass_context
@catch_errors
def discover(ctx, pairs, max_workers):
    '''
    Refresh collection cache for the given pairs.
    '''
    general, all_pairs, all_storages = ctx.obj['config']
    cli_logger.debug('Using {} maximal workers.'.format(max_workers))
    wq = WorkerQueue(max_workers)

    for pair in (pairs or all_pairs):
        try:
            name_a, name_b, pair_options = all_pairs[pair]
        except KeyError:
            raise CliError('Pair not found: {}\n'
                           'These are the pairs found: {}'
                           .format(pair, list(all_pairs)))

        wq.spawn_worker()
        wq.put(functools.partial(
            (lambda wq, **kwargs: collections_for_pair(**kwargs)),
            status_path=general['status_path'], name_a=name_a, name_b=name_b,
            pair_name=pair, config_a=all_storages[name_a],
            config_b=all_storages[name_b], pair_options=pair_options,
            skip_cache=True
        ))

    wq.join()