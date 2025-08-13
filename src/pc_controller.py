# pc_controller.py
# 2025-08-10 v5.0: Added a 3-second delay for window preparation.
# 라즈베리 파이에 시리얼 통신으로 키보드 입력 명령을 전송하는 스크립트

import serial
import time

# !!! 중요 !!!
# 라즈베리 파이 연결 시 장치 관리자의 '포트 (COM & LPT)' 항목에 새로 생긴
# 'USB Serial Device'의 COM 포트 번호로 변경해야 합니다. (예: 'COM3', 'COM4')
RPI_COM_PORT = 'COM4'

def connect_to_pi(port):
    """라즈베리 파이의 시리얼 포트에 연결을 시도합니다."""
    try:
        # baudrate를 115200으로 높여 통신 속도를 개선할 수 있습니다.
        ser = serial.Serial(port, 9600, timeout=1)
        print(f"Successfully connected to Raspberry Pi on {port}")
        time.sleep(1) # 라즈베리 파이가 준비될 때까지 잠시 대기
        return ser
    except serial.SerialException as e:
        print(f"Error: Could not open port {port}.")
        print("Please check the COM port number in Device Manager.")
        print(e)
        return None

def send_command(ser, command):
    """라즈베리 파이에 명령어를 전송하고 출력합니다."""
    print(f"Sending: {command}")
    # 명령어 끝에 개행 문자를 추가하여 명령어의 끝을 알립니다.
    ser.write((command + '\n').encode('utf-8'))
    # 라즈베리 파이가 명령어를 처리할 시간을 줍니다.
    time.sleep(0.05)

def main():
    """메인 함수: 라즈베리 파이에 연결하고 지정된 테스트 케이스를 실행합니다."""
    ser = connect_to_pi(RPI_COM_PORT)

    if not ser:
        return # 연결 실패 시 종료

    # **--[ 변경된 부분 시작 ]--**
    print("\n연결 성공! 2초 후 테스트를 시작합니다. 준비할 창을 활성화해주세요.")
    time.sleep(2) # 창 준비를 위한 3초 대기
    # **--[ 변경된 부분 끝 ]--**

    print("----------------------------------------------------")
    print("테스트 케이스를 실행합니다.")
    print("우측 방향키 2초 누르기 -> Alt + Shift 누르기 -> 모두 떼기")
    print("----------------------------------------------------")

    try:
        # 1. 우측 방향키를 2초 동안 눌렀다가 떼기
        send_command(ser, "d:right") # d for down
        time.sleep(2)
        send_command(ser, "u:right") # u for up
        
        time.sleep(1) # 동작 구분을 위한 1초 대기

        # 2. Alt와 Shift를 동시에 눌렀다가 떼기
        send_command(ser, "d:alt")
        send_command(ser, "d:shift")
        
        time.sleep(1) # 1초 동안 누르고 있기

        # 3. 모든 키 떼기 (순서는 상관 없음)
        send_command(ser, "u:alt")
        send_command(ser, "u:shift")

        print("\n테스트 완료. Closing connection.")

    except Exception as e:
        print(f"An error occurred during communication: {e}")
    finally:
        if ser:
            ser.close()

if __name__ == "__main__":
    main()
