import serial
from serial.tools import list_ports


class SerialService:
    """
    极简串口封装：只负责「打开 / 关闭 / 发送单个 0/1 字符」。
    不做协议、不做重连、不做策略。
    """
    def __init__(self):
        self._ser: serial.Serial | None = None
        self._sent_count = 0
        self._error_count = 0

    # ---- 端口枚举（供 GUI 下拉框刷新） ----
    @staticmethod
    def list_ports() -> list[dict]:
        return [{"device": p.device, "desc": p.description}
                for p in list_ports.comports()]

    # ---- 打开 / 关闭 ----
    def open(self, port: str, baudrate: int = 115200) -> tuple[bool, str]:
        if self._ser and self._ser.is_open:
            self._ser.close()
        try:
            self._ser = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=8,
                parity="N",
                stopbits=1,
                timeout=0.05,
                write_timeout=0.2,
            )
            return True, f"已打开 {port} @ {baudrate}"
        except serial.SerialException as e:
            self._ser = None
            return False, str(e)

    def close(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._ser = None

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    # ---- 发送 ----
    def send_value(self, value: int) -> tuple[bool, str]:
        """向 Arduino 发送单字符：命中 '1'，未命中 '0'。"""
        if not self.is_open:
            self._error_count += 1
            return False, "串口未打开"
        data = b"1" if value == 1 else b"0"
        try:
            self._ser.write(data)
            self._ser.flush()
            self._sent_count += 1
            return True, data.decode()
        except serial.SerialException as e:
            self._error_count += 1
            return False, str(e)

    @property
    def stats(self) -> dict:
        return {"sent": self._sent_count, "errors": self._error_count}