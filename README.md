# ThaiElement · ธาตุไท 🌿

## วิธีติดตั้งและรัน

### ความต้องการ
- Python 3.8+

### ติดตั้ง dependencies
```bash
pip install flask flask-cors flask-jwt-extended bcrypt
```

### รันเซิร์ฟเวอร์
```bash
python server.py
```

เปิดเบราว์เซอร์ที่ **http://localhost:5055**

---

## โครงสร้างฐานข้อมูล SQLite (`thaielement.db`)

| ตาราง | คำอธิบาย |
|-------|----------|
| `users` | บัญชีผู้ใช้ (username, email, password hash) |
| `profiles` | ข้อมูลส่วนตัว (ชื่อ, เพศ, วันเกิด, ธาตุเจ้าเรือน) |
| `onboarding_answers` | คำตอบแบบสอบถามแรกเข้า |
| `elements` | ค่าธาตุ 4 แต่ละวัน (fire/water/wind/earth) |
| `checkins` | Quick check-in ประจำวัน |
| `sleep_logs` | บันทึกการนอน |
| `food_logs` | บันทึกอาหาร + รสยา |
| `excretion_logs` | บันทึกการขับถ่าย |
| `challenges` | ภารกิจที่เข้าร่วม |
| `symptoms` | อาการจาก Daily Scan |
