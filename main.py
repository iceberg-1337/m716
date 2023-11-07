import json
import random
import time
import csv
import os
from datetime import datetime


import paramiko  # pip install paramiko
import click  # pip install click
from halo import Halo  # pip install halo

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

if not os.path.exists('results'):
    os.makedirs('results')

dir = os.getcwd().replace('\\', '/') + '/results'

with open('config.json', 'r') as config_file:
    config = json.load(config_file)

rpi = config['rpi']
M716 = config['m716']
rpi_conf = config['rpi_conf']
user = config['user']
port_cfg = config['port_cfg']
total_speed = []


def raspberry(flows, delays, jitters, losses):
    ssh_rpi = paramiko.SSHClient()
    ssh_rpi.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_rpi.connect(rpi['address'], username=rpi['user'], password=rpi['password'])
    commands = ['su', rpi['root'], 'apt-get install bridge-utils', 'apt-get install iproute2',
                'brctl addbr br0', 'brctl addif br0 eth0', 'brctl addif br0 eth1', 'ifconfig br0 up',
                'tc qdisc del dev eth1 root']

    with ssh_rpi.invoke_shell() as ssh:
        for command in commands:
            ssh.send(command + '\n')
            time.sleep(1)
        ssh.send('tc qdisc replace dev eth1 root handle 1: htb default 10\n')
        for dport in range(1, flows+1):
            ssh.send(f'tc class replace dev eth1 parent 1: classid 1:{dport+10} htb rate 1Gbit\n')
            time.sleep(0.01)
            ssh.send(f'tc filter replace dev eth1 protocol ip prio 1 u32 match ip dport {dport+60000} 0xffff flowid 1:{dport+10}\n')
            time.sleep(0.01)
            ssh.send(f'tc qdisc replace dev eth1 parent 1:{dport+10} handle {dport+10}: netem delay {delays[dport-1]}ms {jitters[dport-1]}ms loss {losses[dport-1]}%\n')
            time.sleep(0.01)
        time.sleep(1)


def m716(flows, timer):
    commands_anlz = ['su', M716['root'], 'cd', 'insmod multiflows_trafgen.ko', 'insmod multiflows_anlz.ko',
                     f'manlz.py -t {timer} -j anlz.json -l {(rpi_conf["delay"] + rpi_conf["jitter"]) * 1000}'
                     f' {rpi_conf["jitter"] * 1000}']

    commands_gen = ['su', M716['root'], 'cd',
                    f'scp {user["user"]}@{user["address"]}:{dir}/port1.ini port1.ini',
                    f'{user["password"]}', 'mgen.py -clear -p 0', 'mgen.py -c port1.ini -p 0',
                    'mgen.py -s -p 0', 'mgen.py -f -p 0', 'mgen.py -j gen.json -p0']

    mac_list = ["a", "b", "c", "d", "e", "f", '0', '1', '2', '3', '4', '5', '6', '7', '8', '9']

    ssh_m716 = paramiko.SSHClient()
    ssh_m716.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_m716.connect(M716['address'], username=M716['user'], password=M716['password'])

    with open('results/port1.ini', 'w') as file:
        for index in range(1, flows + 1):
            pkt_size = random.randint(128, 1500) if port_cfg['pkt_size'] == 'rnd' else port_cfg['pkt_size']
            speed = random.randint(150000, 1000000) if port_cfg['speed'] == 'rnd' else port_cfg['speed']
            total_speed.append(speed)
            mac_s = f'00:22:ce:00:0{random.choice(mac_list)}:{random.choice(mac_list)}{random.choice(mac_list)}' if \
                port_cfg['macs'] == 'rnd' else port_cfg['macs']
            mac_d = f'00:22:ce:2c:0{random.choice(mac_list)}:{random.choice(mac_list)}{random.choice(mac_list)}' if \
                port_cfg['macd'] == 'rnd' else port_cfg['macd']
            ip_s = ".".join(map(str, (random.randint(0, 255) for _ in range(4)))) if port_cfg['ips'] == 'rnd' else \
                port_cfg['ips']
            ip_d = ".".join(map(str, (random.randint(0, 255) for _ in range(4)))) if port_cfg['ipd'] == 'rnd' else \
                port_cfg['ipd']
            ups = random.randint(49152, 65535) if port_cfg['ups'] == 'rnd' else port_cfg['ups']
            upd = 60000 + index
            index_template = template.format(index, pkt_size, speed, mac_s, mac_d, ip_s, ip_d, ups, upd)
            file.write(index_template)

    with ssh_m716.invoke_shell() as ssh_anlz:
        for command in commands_anlz:
            ssh_anlz.send(command + '\n')
            time.sleep(1)
        time.sleep(15)
        with ssh_m716.invoke_shell() as ssh_gen:
            for command in commands_gen:
                ssh_gen.send(command + '\n')
                if command == 'mgen.py -s -p 0':
                    time.sleep(timer/2)
                time.sleep(3)
        time.sleep(timer/2 + 10)


def get_results():
    ssh_m716 = paramiko.SSHClient()
    ssh_m716.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_m716.connect(M716['address'], username=M716['user'], password=M716['password'])
    commands = ['su', M716["root"], 'cd', f'scp anlz.json {user["user"]}@{user["address"]}:{dir}',
                user['password'], f'scp gen.json {user["user"]}@{user["address"]}:{dir}',
                user['password']]
    with ssh_m716.invoke_shell() as ssh:
        for command in commands:
            ssh.send(command + '\n')
            time.sleep(5)


status = []


def results(flows, delays, jitters, losses):
    with open('results/gen.json', 'r') as file:
        data = json.load(file)
    filtered_data_gen = [block for block in data if block['PKTS'] != 0]
    with open('results/gen.json', 'w') as file:
        json.dump(filtered_data_gen, file, indent=2)

    with open('results/anlz.json', 'r') as file:
        data = json.load(file)
    filtered_data_test = [block for block in data if block['FlowId'] != 0]
    with open('results/anlz.json', 'w') as file:
        json.dump(filtered_data_test, file, indent=2)

    flow_ids = [d['FlowId'] for d in filtered_data_test]
    set_delay = []
    received_delay = []
    set_jitter = []
    recieved_jitter = []
    set_loss = []
    received_loss = []

    print(f'Итоговая скорость: {sum(total_speed) / 1000000} Мбит/с')
    if len(filtered_data_test) != flows:
        print('Количество потоков отличается от сгенерированных')
        missing_flow_ids = [flow_id for flow_id in range(1, flows+1) if flow_id not in flow_ids]
        print('Отсутсвующие потоки: ', missing_flow_ids)
    else:
        print('Количество потоков совпадает с генератором')

    for params in filtered_data_test:
        success = True
        flow = params['FlowId'] - 1
        set_delay.append(delays[flow] + jitters[flow])
        received_delay.append(round(params['PrevLat']/1000, 1))
        if round(params['PrevLat']/1000, 1) > (delays[flow] + jitters[flow] + 1.1):
            print(f'в потоке {params["FlowId"]} задержка больше установленной, установленная {delays[flow] + jitters[flow]},'
                  f' полученная {params["PrevLat"]/1000}')
            success = False
        loss = round((params['PrevSeqNum'] - params['PktsCnt']) * 100 / params['PrevSeqNum'], 1)
        set_loss.append(losses[flow])
        received_loss.append(loss)
        if loss > losses[flow] + 1:
            print(f'в потоке {params["FlowId"]} процент потерь больше установленного, установленный {losses[flow]},'
                  f'полученный {loss}')
            success = False
        total_jitter = 0
        total_weight = 0
        interval = jitters[flow] / 8
        for i, value in enumerate(params['JitDistr']):
            mid_interval = (i + 0.5) * interval  # Середина интервала корзины
            total_jitter += value * mid_interval
            total_weight += value
        average_jitter = (round(total_jitter / total_weight, 1)) if total_weight != 0 else 0
        set_jitter.append(jitters[flow])
        recieved_jitter.append(average_jitter)
        if average_jitter > jitters[flow] + 1:
            print(f'в потоке {params["FlowId"]} джиттер больше установленного, установленный {jitters[flow]},'
                  f'полученный {average_jitter}')
            success = False
        if success:
            status.append('OK')
        else:
            status.append('FAILED')

    with open('results/results.csv', "w", encoding="UTF-8") as file:
        file_writer = csv.writer(file, delimiter=";", lineterminator="\r")
        headers = ["Number of flow", "set delay", "received delay", "set jitter", "received jitter",
                   "set loss", "received loss", "status"]
        file_writer.writerow(headers)
        for i in range(len(flow_ids)):
            file_writer.writerow([flow_ids[i], set_delay[i], received_delay[i], set_jitter[i], recieved_jitter[i],
                                 set_loss[i], received_loss[i], status[i]])


def total_result(flows):
    if 'FAILED' in status:
        result = 'FAILED'
    else:
        result = 'OK'
    if not os.path.isfile('total_results.csv'):
        with open('total_results.csv', "w", encoding="UTF-8") as file:
            file_writer = csv.writer(file, delimiter=";", lineterminator="\r")
            headers = ["Flows", "speed", "packet size", "set delay", "set jitter",
                       "set loss", "status"]
            file_writer.writerow(headers)
            file_writer = csv.writer(file, delimiter=";", lineterminator="\r")
            file_writer.writerow([flows, sum(total_speed) / 1000000, port_cfg['pkt_size'], rpi_conf['delay'],
                                  rpi_conf['jitter'], rpi_conf['loss'], result])
    else:
        with open('total_results.csv', "a", encoding="UTF-8") as file:
            file_writer = csv.writer(file, delimiter=";", lineterminator="\r")
            file_writer.writerow([flows, sum(total_speed) / 1000000, port_cfg['pkt_size'], rpi_conf['delay'],
                                  rpi_conf['jitter'], rpi_conf['loss'], result])


@click.command()
@click.option('--flows', type=click.IntRange(1, 1000), required=True, help='Number of flows')
@click.option('--timer', type=click.INT, required=True, help='time for test')
def main(flows, timer):
    start = datetime.now()
    print(start)
    delays = [random.randint(rpi_conf['jitter'], rpi_conf['delay']) for _ in range(flows)]
    jitters = [random.randint(0, rpi_conf['jitter']) for _ in range(flows)]
    losses = [round(random.uniform(0, rpi_conf['loss']), 1) for _ in range(flows)]
    with Halo(text='Настройка Raspberry', spinner='moon'):
        raspberry(flows, delays, jitters, losses)
    with Halo(text='Настройка M716', spinner='moon'):
        m716(flows, timer)
    with Halo(text='Получение результатов', spinner='moon'):
        get_results()
    results(flows, delays, jitters, losses)
    total_result(flows)

    stop = datetime.now()
    print(stop)


if __name__ == "__main__":
    main()
