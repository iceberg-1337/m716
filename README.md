# M716 autotest
script for testing a multiflows generator and analyzer on the m716 device

## Installation 
Use the package manager [pip](https://pip.pypa.io/en/stable/) to install 

```bash
pip install -r requirements.txt
```

## Usage
1. configure config.json with your params
2. run script with params:
- `--flows`, number of flows
- `--timer`, analyzer and generator operating time

``` bash
python main.py --flows 1000 --timer 60
```

