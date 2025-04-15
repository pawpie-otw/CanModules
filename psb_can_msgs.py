import can
import time
import struct
try:
    from .logger import logger
except ImportError:
    from logger import logger


def get_bit_by_idx(num, idx):
    return (num >> idx) & 1


def is_bit_at(num, idx):
    return bool(get_bit_by_idx(num, idx))


class ReceiveTimeout(Exception):
    ...


class CycleReadIdAllocations:
    BASE_ID_CYCLE_READ = 0x100
    STATUS = BASE_ID_CYCLE_READ
    ACTUAL_VALUES = 0x101
    SET_VALUES_PS = 0x102
    LIMITS_1_PS = 0x103
    LIMITS_2_PS = 0x104
    SET_VALUES_EL = 0x105
    LIMITS_1_EL = 0x106


class CycleSendIdAllocations:
    BASE_ID_CYCLE_SEND = 0x200
    CONTROL = BASE_ID_CYCLE_SEND
    SET_VALUES_1_PS = 0x201
    SET_VALUES_1_EL = 0x202


class PsbCanMsgs:

    NOMINAL = {'u': 1000,
               'i': 80,
               'p': 30_000,
               'r': 1}

    VALUE_SCALE = {'p': 0.572213321,
                   'u': 0.019073777,
                   'i': 0.001525902,
                   'r': 0.012397955}

    DEVICES_AMOUNT = 3

    def __init__(self,
                 set_sour_values=None,
                 set_sink_values=None,
                 device_amount=3):
        """To set new params on device use one of :
            `set_sour_params`, `set_sink_params`, 
            `remote_on`, `remote_off`,
            `output_on`, `output_off`.
        Then updated msg will be assigned to:
            `_set_sour_msg`,
            `_set_sink_msg`,
            `_set_status_msg`.
            or:
            set_msgs_map: dict[int, can.Message]
        """

        if set_sour_values is None:
            set_sour_values = {}
        if set_sink_values is None:
            set_sink_values = {}

        self._set_sour_params = {'u': 0,
                                 'i': 0,
                                 'p': 0,
                                 'r': 0}
        self._set_sour_params.update(set_sour_values)
        self._set_sink_params = {'i': 0,
                                 'p': 0,
                                 'r': 0}
        self._set_sink_params.update(set_sink_values)
        self._set_status_params = {'remote_control': 1,
                                   'output': 0}
        self.DEVICES_AMOUNT = device_amount

        self._set_status_msg = self._status_msg(**self._set_status_params)
        self._set_sour_msg = self._set_sour_values(**self._set_sour_params)
        self._set_sink_msg = self._set_sink_values(**self._set_sink_params)

        self.set_msgs_map = {CycleSendIdAllocations.CONTROL: self._set_status_msg,
                             CycleSendIdAllocations.SET_VALUES_1_PS: self._set_sour_msg,
                             CycleSendIdAllocations.SET_VALUES_1_EL: self._set_sink_msg}
        self.supported_read_can_ids = (CycleReadIdAllocations.ACTUAL_VALUES,
                                       CycleReadIdAllocations.STATUS,
                                       CycleReadIdAllocations.SET_VALUES_PS,
                                       CycleReadIdAllocations.SET_VALUES_EL)
        self._prev_recv_time = {k: time.time()
                                for k in self.supported_read_can_ids}
        self._actual_vals = {}
        self._set_sour_vals = {}
        self._set_sink_vals = {}
        self._status_vals = {}

    @property
    def actual_vals(self):
        return self._actual_vals

    @property
    def set_sour_vals(self):
        return self._set_sour_vals

    @property
    def set_sink_vals(self):
        return self._set_sink_vals

    @property
    def status_vals(self):
        return self._status_vals

    "High level set methods"

    @logger.log_decore_wres
    def set_sour_params(self, u=None, i=None, p=None, r=0):
        if u is not None:
            self._set_sour_params['u'] = u
        if i is not None:
            self._set_sour_params['i'] = i
        if p is not None:
            self._set_sour_params['p'] = p
        if r is not None:
            self._set_sour_params['r'] = r
        return self.update_set_sour_msg()

    @logger.log_decore_wres
    def set_sink_params(self, u=None, i=None, p=None, r=0):
        if u is not None:
            self.set_sour_params(u=u)
        if i is not None:
            self._set_sink_params['i'] = i
        if p is not None:
            self._set_sink_params['p'] = p
        if r is not None:
            self._set_sink_params['r'] = r
        return self.update_set_sink_msg()

    @logger.log_decore_wres
    def remote_on(self):
        self._set_status_params['remote_control'] = 1
        return self.update_status_msg()

    @logger.log_decore_wres
    def remote_off(self):
        self._set_status_params['remote_control'] = 0
        return self.update_status_msg()

    @logger.log_decore_wres
    def output_on(self):
        self._set_status_params['output'] = 1
        return self.update_status_msg()

    @logger.log_decore_wres
    def output_off(self):
        self._set_status_params['output'] = 0
        return self.update_status_msg()

    @logger.log_decore_wres
    def get_actual_values(self):
        return self._curr_vals

    "update msg methods"

    def update_set_sour_msg(self):
        self._set_sour_msg = self._set_sour_values(**self._set_sour_params)
        self.set_msgs_map[CycleSendIdAllocations.SET_VALUES_1_PS] = self._set_sour_msg
        return self._set_sour_msg

    def update_set_sink_msg(self):
        self._set_sink_msg = self._set_sink_values(**self._set_sink_params)
        self.set_msgs_map[CycleSendIdAllocations.SET_VALUES_1_EL] = self._set_sink_msg
        return self._set_sink_msg

    def update_status_msg(self):
        self._set_status_msg = self._status_msg(**self._set_status_params)
        self.set_msgs_map[CycleSendIdAllocations.CONTROL] = self._set_status_msg
        return self._set_status_msg

    " Create Msg methods "

    @classmethod
    def _status_msg(cls, output: bool, remote_control: bool = 1):
        value = output*2+remote_control
        return can.Message(arbitration_id=CycleSendIdAllocations.CONTROL,
                           dlc=8,
                           data=struct.pack('>H', value << 8))

    @classmethod
    def _set_sour_values(cls, u, i, p=None, r=0):
        if p is None:
            p = u * i
        u = int(u/cls.VALUE_SCALE['u'])
        i = int(i/cls.VALUE_SCALE['i']/cls.DEVICES_AMOUNT)
        p = int(p/cls.VALUE_SCALE['p']/cls.DEVICES_AMOUNT)
        return can.Message(arbitration_id=CycleSendIdAllocations.SET_VALUES_1_PS,
                           dlc=8,
                           data=struct.pack('>HHHH', u, i, p, r))

    @classmethod
    def _set_sink_values(cls, i, p, r=0):
        i = int(i/cls.VALUE_SCALE['i']/cls.DEVICES_AMOUNT)
        p = int(p/cls.VALUE_SCALE['p']/cls.DEVICES_AMOUNT)
        msg = can.Message(arbitration_id=CycleSendIdAllocations.SET_VALUES_1_EL,
                          dlc=8,
                          data=struct.pack('>HHH', i, p, r))
        return msg

    def longest_time_since_recv(self):
        return max(self._prev_recv_time.values())

    "Decode methods"

    def decode_if_supported(self, msg):
        if msg.arbitration_id in self.supported_read_can_ids:
            return self.decode_msg(msg)
        return False

    def decode_msg(self, msg: can.Message):
        try:
            decode_method_map = {CycleReadIdAllocations.ACTUAL_VALUES: self._decode_actual_values,
                                 CycleReadIdAllocations.STATUS: self._decode_status_msg,
                                 CycleReadIdAllocations.SET_VALUES_PS: self._decode_set_sour_values,
                                 CycleReadIdAllocations.SET_VALUES_EL: self._decode_set_sink_values}
            self._prev_recv_time[msg.arbitration_id] = time.time()
            return decode_method_map[msg.arbitration_id](msg)
        except KeyError:
            raise ValueError(
                f'This can-id {msg.arbitration_id} is not supported or is wrong.')

    @logger.log_decore_wres
    def _decode_actual_values(self, msg):
        if msg.arbitration_id != CycleReadIdAllocations.ACTUAL_VALUES:
            raise ValueError('Wrong arbitration id.')
        u, i, p = struct.unpack('>HHH', msg.data[:6])
        vals = {'u': u*self.VALUE_SCALE['u'],
                'i': i*self.VALUE_SCALE['i']*self.DEVICES_AMOUNT,
                'p': p*self.VALUE_SCALE['p']*self.DEVICES_AMOUNT}
        self._actual_vals.update(vals)
        return vals

    @logger.log_decore_wres
    def _decode_status_msg(self, msg: can.Message) -> dict:
        """Returns dicted flags."""
        if msg.arbitration_id != CycleReadIdAllocations.STATUS:
            raise ValueError('Wrong arbitration id.')
        data_int = int.from_bytes(msg.data, byteorder='big')
        vals = {'remote_control': is_bit_at(data_int, 31),
                'dc_input_terminal': is_bit_at(data_int, 30),
                'uir_mode': not is_bit_at(data_int, 28),
                'uip_mode': is_bit_at(data_int, 28),
                'alarms': is_bit_at(data_int, 27),
                'alarm_msp_map': is_bit_at(data_int, 26),
                'alarm_ocd': is_bit_at(data_int, 25),
                'alarm_ocp': is_bit_at(data_int, 24),
                # 'interface_in_access': is_bit_at(..., 23...19)
                'alarm_opd': is_bit_at(data_int, 18),
                'alarm_opp': is_bit_at(data_int, 17),
                'alarm_ot': is_bit_at(data_int, 16),
                'alarm_ovd': is_bit_at(data_int, 14),
                'alarm_ovp': is_bit_at(data_int, 13),
                # 'alarm_pf': is_bit_at(data_int, 12..10),
                'rem_sb': is_bit_at(data_int, 9),
                'alarm_ucd': is_bit_at(data_int, 8),
                'alarm_uvd': is_bit_at(data_int, 7),
                'external_remote_sensing': is_bit_at(data_int, 6),
                'internal_remote_sensing': not is_bit_at(data_int, 6),
                'function_gen_active': is_bit_at(data_int, 5),
                'master': is_bit_at(data_int, 4),
                'slave': not is_bit_at(data_int, 4),
                'input_output': is_bit_at(data_int, 3),
                # 'regulation_mode': is_bit_at(data_int, 2...1),
                'sink_mode': is_bit_at(data_int, 0),
                'sour_mode': not is_bit_at(data_int, 0)}
        self._status_vals.update(vals)
        return vals

    @logger.log_decore_wres
    def _decode_set_sour_values(self, msg: can.Message) -> dict:
        # print('decoding set sour values')
        if msg.arbitration_id != CycleReadIdAllocations.SET_VALUES_PS:
            raise ValueError(
                f'Wrong arbitration id. Expected {CycleReadIdAllocations.SET_VALUES_PS}, got {msg.arbitration_id}')

        u, i, p, r = struct.unpack('<HHHH', msg.data)
        # print(msg.arbitration_id, msg.data)
        vals = {'u': u*self.VALUE_SCALE['u'],
                'i': i*self.VALUE_SCALE['i']*self.DEVICES_AMOUNT,
                'p': p*self.VALUE_SCALE['p']*self.DEVICES_AMOUNT,
                'r': r*self.VALUE_SCALE['r']}
        # print(vals)
        self._set_sour_vals.update(vals)
        return vals

    @logger.log_decore_wres
    def _decode_set_sink_values(self, msg: can.Message) -> dict:
        if msg.arbitration_id != CycleReadIdAllocations.SET_VALUES_EL:
            raise ValueError(
                f'Wrong arbitration id. Expected {CycleReadIdAllocations.SET_VALUES_EL}, got {msg.arbitration_id}')
        i, p, r = struct.unpack('<HHH', msg.data)
        vals = {'i': i*self.VALUE_SCALE['i']*self.DEVICES_AMOUNT,
                'p': p*self.VALUE_SCALE['p']*self.DEVICES_AMOUNT,
                'r': r*self.VALUE_SCALE['r']}
        self._set_sink_vals.update(vals)
        return vals


if __name__ == '__main__':
    psb = PsbCanMsgs()
