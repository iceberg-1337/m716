import json
import random
import time

import paramiko  # pip install paramiko
import click  # pip install click

template = """[{0}]
pkt_size = {1}
speed = {2}
init = 1
macs = {3}
macd = {4}
ips = {5}
ipd = {6}
ups = {7}
upd = {8}
"""


def load_config(file_path):
    with open(file_path, 'r') as config_file:
        return json.load(config_file)


config = load_config('config.json')

rpi = config['rpi']
M716 = config['m716']
rpi_conf = config['rpi_conf']
user = config['user']
port_cfg = config['port_cfg']


def raspberry():
    ssh_rpi = paramiko.SSHClient()
    ssh_rpi.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_rpi.connect(rpi['address'], username=rpi['user'], password=rpi['password'])
    commands = ['su', rpi['root'], 'apt-get install bridge-utils', 'apt-get install iproute2',
                f'tc qdisc replace dev eth1 root netem delay {rpi_conf["delay"]}ms {rpi_conf["jitter"]}ms loss'
                f' {rpi_conf["loss"]}%',
                'brctl addbr br0', 'brctl addif br0 eth0', 'brctl addif br0 eth1', 'ifconfig br0 up']
    with ssh_rpi.invoke_shell() as ssh:
        for command in commands:
            ssh.send(command + '\n')
            time.sleep(1)
    print(ssh.recv(600000).decode("utf-8"))


def m716(flows, timer):
    commands_anlz = ['su', M716['root'], 'cd', 'insmod multiflows_trafgen.ko', 'insmod multiflows_anlz.ko',
                     f'manlz.py -t {timer} -j anlz.json -l {(rpi_conf["delay"] + rpi_conf["jitter"]) * 1000}'
                     f' {rpi_conf["jitter"] * 1000}']

    commands_gen = ['su', M716['root'], 'cd',
                    f'scp {user["user"]}@{user["address"]}:{user["dir"]}/port1.ini port1.ini',
                    f'{user["password"]}', 'mgen.py -clear -p 0', 'mgen.py -c port1.ini -p 0',
                    'mgen.py -s -p 0', 'mgen.py -f -p 0', 'mgen.py -j gen.json -p0']

    mac_list = ["a", "b", "c", "d", "e", "f", '0', '1', '2', '3', '4', '5', '6', '7', '8', '9']

    ssh_m716 = paramiko.SSHClient()
    ssh_m716.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_m716.connect(M716['address'], username=M716['user'], password=M716['password'])

    with open('port1.ini', 'w') as file:
        for index in range(1, flows + 1):
            pkt_size = random.randint(128, 1500) if port_cfg['pkt_size'] == 'rnd' else port_cfg['pkt_size']
            speed = random.randint(10000, 1000000) if port_cfg['speed'] == 'rnd' else port_cfg['speed']
            mac_s = f'00:22:ce:00:0{random.choice(mac_list)}:{random.choice(mac_list)}{random.choice(mac_list)}' if \
                port_cfg['macs'] == 'rnd' else port_cfg['macs']
            mac_d = f'00:22:ce:2c:0{random.choice(mac_list)}:{random.choice(mac_list)}{random.choice(mac_list)}' if \
                port_cfg['macd'] == 'rnd' else port_cfg['macd']
            ip_s = ".".join(map(str, (random.randint(0, 255) for _ in range(4)))) if port_cfg['ips'] == 'rnd' else \
                port_cfg['ips']
            ip_d = ".".join(map(str, (random.randint(0, 255) for _ in range(4)))) if port_cfg['ipd'] == 'rnd' else \
                port_cfg['ipd']
            ups = random.randint(49152, 65535) if port_cfg['ups'] == 'rnd' else port_cfg['ups']
            upd = random.randint(49152, 65535) if port_cfg['upd'] == 'rnd' else port_cfg['upd']
            index_template = template.format(index, pkt_size, speed, mac_s, mac_d, ip_s, ip_d, ups, upd)
            file.write(index_template)

    with ssh_m716.invoke_shell() as ssh_anlz:
        for command in commands_anlz:
            ssh_anlz.send(command + '\n')
            time.sleep(1)
        time.sleep(15)
        print(ssh_anlz.recv(60000).decode('utf-8'))
        with ssh_m716.invoke_shell() as ssh_gen:
            for command in commands_gen:
                ssh_gen.send(command + '\n')
                if command == 'mgen.py -s -p 0':
                    time.sleep(timer/2)
                time.sleep(3)
            print(ssh_gen.recv(60000).decode('utf-8'))
        time.sleep(timer/2 + 10)
        print(ssh_anlz.recv(60000).decode('utf-8'))


def get_results():
    ssh_m716 = paramiko.SSHClient()
    ssh_m716.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_m716.connect(M716['address'], username=M716['user'], password=M716['password'])
    commands = ['su', M716["root"], 'cd', f'scp anlz.json {user["user"]}@{user["address"]}:{user["dir"]}',
                user['password'], f'scp gen.json {user["user"]}@{user["address"]}:{user["dir"]}',
                user['password']]
    with ssh_m716.invoke_shell() as ssh:
        for command in commands:
            ssh.send(command + '\n')
            time.sleep(5)
        print(ssh.recv(60000).decode('utf-8'))


def results(flows):
    with open('gen.json', 'r') as file:
        data = json.load(file)
    filtered_data_gen = [block for block in data if block['PKTS'] != 0]
    with open('gen.json', 'w') as file:
        json.dump(filtered_data_gen, file, indent=2)
    pkts_gen = sum(s['PKTS'] for s in filtered_data_gen)

    with open('anlz.json', 'r') as file:
        data = json.load(file)
    filtered_data_test = [block for block in data if block['FlowId'] != 0]
    with open('anlz.json', 'w') as file:
        json.dump(filtered_data_test, file, indent=2)
    pkts_anlz = sum(s['PktsCnt'] for s in filtered_data_test)

    loss = ((pkts_gen - pkts_anlz) * 100) / pkts_gen
    if loss > rpi_conf['loss'] + 1:
        print('Процент потерь выше установленного ', f'{loss} %')
    else:
        print('процент потерь соответсвует установленному')

    if len(filtered_data_test) != flows:
        print('Количество потоков отличается от сгенерированных')
        flow_ids = [d['FlowId'] for d in filtered_data_test]
        missing_flow_ids = [flow_id for flow_id in range(1, flows+1) if flow_id not in flow_ids]
        print('Отсутсвующие потоки: ', missing_flow_ids)
    else:
        print('Количество потоков совпадает с генератором')

    for params in filtered_data_test:
        if params['PrevLat'] > (rpi_conf['delay'] + rpi_conf['jitter'] + 1) * 1000:
            print(f'в потоке {params["FlowId"]} задержка больше установленной')


@click.command()
@click.option('--flows', type=click.IntRange(1, 1000), required=True, help='Number of flows')
@click.option('--timer', type=click.INT, required=True, help='time for test')
def main(flows, timer):
    raspberry()
    m716(flows, timer)
    get_results()
    results(flows)


if __name__ == "__main__":
    main()
