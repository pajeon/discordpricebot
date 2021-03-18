import json
import os
from decimal import Decimal
from urllib.request import urlopen, Request


def fetch_abi(contract):
    if not os.path.exists('contracts'):
        os.mkdir('./contracts')

    filename = f'contracts/{contract}.json'
    if os.path.exists(filename):
        with open(filename, 'r') as abi_file:
            abi = abi_file.read()
    else:
        # TODO: Error handling
        url = 'https://api.bscscan.com/api?module=contract&action=getabi&address=' + contract
        abi_response = urlopen(
            Request(url, headers={'User-Agent': 'Mozilla'})).read().decode('utf8')
        abi = json.loads(abi_response)['result']

        with open(filename, 'w') as abi_file:
            abi_file.write(abi)

    return json.loads(abi)


def list_cogs(directory, file=__file__):
    basedir = (os.path.basename(os.path.dirname(file)))
    return (f"{basedir}.{directory}.{f.rstrip('.py')}" for f in os.listdir(basedir + '/' + directory) if f.endswith('.py'))


def shift(decimal, n):
    return decimal * (Decimal('10') ** n)
