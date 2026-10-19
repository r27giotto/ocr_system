const int VALVE_PIN = 8;        // 驱动 MOSFET 栅极（经光耦）
const int LED_PIN   = 13;       // 板载指示灯，跟随脉冲

// ⚠️ 脉冲宽度必须按你的喷气嘴规格调！
// 典型电磁阀响应时间 10~50ms，脉冲太短阀打不开，太长浪费气且发热
const unsigned long PULSE_MS = 100;

unsigned long pulseStart = 0;
bool pulsing = false;

void setup() {
  pinMode(VALVE_PIN, OUTPUT);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(VALVE_PIN, LOW);   // 上电默认关闭，安全
  digitalWrite(LED_PIN, LOW);

  Serial.begin(115200);            // 和 Python 一致（你脚本是 115200）
}

void loop() {
  // 1) 收串口：收到 '1' 就触发一次脉冲，'0' 忽略（或用于急停）
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '1') {
      digitalWrite(VALVE_PIN, HIGH);
      digitalWrite(LED_PIN, HIGH);
      pulseStart = millis();
      pulsing = true;
    } else if (c == '0') {
      // 可选：收到 '0' 立即关闭（急停/复位用）
      digitalWrite(VALVE_PIN, LOW);
      digitalWrite(LED_PIN, LOW);
      pulsing = false;
    }
  }

  // 2) 非阻塞计时：到点自动关阀
  if (pulsing && (millis() - pulseStart >= PULSE_MS)) {
    digitalWrite(VALVE_PIN, LOW);
    digitalWrite(LED_PIN, LOW);
    pulsing = false;
  }
}