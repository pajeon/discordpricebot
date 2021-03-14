import sys
import importlib
from pricebot import pricebot
from boardroombot import boardroombot
import yaml

bots = {}

with open('config.yaml') as cfg_file:
    cfg_data = yaml.safe_load(cfg_file)

cfg_defaults = cfg_data.pop('_config')

if len(sys.argv) < 2:
    print(f"Usage: {sys.argv[0]} <name>")
    sys.exit()

if sys.argv[1] and cfg_data.get(sys.argv[1]):
    cfg_data = {sys.argv[1]: cfg_data.get(sys.argv[1])}
else:
    raise Exception(f"{sys.argv[1]} does not exist in configuration!")

for cfg_name, cfg_info in cfg_data.items():
    common = cfg_info.get('common')
    if not common:
        raise Exception(f"Each instance must have a common configuration")

    token = cfg_info.get('token')
    boardroom = cfg_info.get('boardroom')
    if (not token and not boardroom) or (token and boardroom):
        raise Exception(
            f"Each instance must have one token or boardroom configuration")

    common['name'] = cfg_name

    config = ({**cfg_defaults, **cfg_info.get('config', {})})

    if config.get('plugin'):
        try:
            module = importlib.import_module(config['plugin'])
            bots[cfg_name] = module.PriceBot(config, token)
        except ModuleNotFoundError as e:
            print(f"Token {cfg_name} has an invalid plugin configuration!", e)
            sys.exit()
        except AttributeError:
            print(f"The plugin for {cfg_name} must be named PriceBot!")
            sys.exit()
    else:
        if token:
            instance = pricebot.PriceBot(config, common, token)
        else:
            instance = boardroombot.BoardroomBot(
                config, common, boardroom)
        bots[cfg_name] = instance

    bots[cfg_name].exec()
