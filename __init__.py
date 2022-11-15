import os

try:
    import xmltodict
except:
    try: os.system("pip install xmltodict")
    except: pass

try:
    import yaml
    a = yaml.FullLoader
except:
    try: os.system("pip install --upgrade pyyaml")
    except: pass

