# main_ebtg.py

# 1. 필요한 모듈 임포트
import argparse
import sys
import logging # 애플리케이션 로깅을 위해

# EBTG GUI 모듈 (GUI 모드 선택 시 동적 임포트)
# from ebtg.gui.ebtg_gui import EbtgGui # 실제 임포트는 run_gui_application 함수 내에서 수행

# CLI 모드용 플레이스홀더 클래스 (명확성을 위해 이름 변경)
class EBTG_Placeholder_CLI:
    def __init__(self, config_path):
        self.config_path = config_path
        logging.info(f"EBTG CLI 인스턴스가 설정 파일 '{config_path}'로 초기화되었습니다.")
        # 여기서 실제 설정 파일을 읽고 초기화하는 로직이 들어갈 수 있습니다.

    def run(self):
        logging.info("EBTG CLI의 핵심 로직을 실행합니다...")
        # 여기에 애플리케이션의 주된 작업이 수행됩니다.
        # 예를 들어, 이벤트 기반으로 트레이스를 생성하는 로직 등
        logging.info("이것은 현재 플레이스홀더 CLI 구현입니다.")
        return "핵심 로직 실행 완료 (결과 예시)"

def run_gui_application():
    """EBTG GUI 애플리케이션을 로드하고 실행합니다."""
    logging.info("GUI 모드로 EBTG 애플리케이션을 시작합니다...")
    try:
        import tkinter as tk
        from ebtg.gui.ebtg_gui import EbtgGui # main_ebtg.py가 프로젝트 루트에 있다고 가정

        # EbtgGui 클래스가 자체적으로 상세 로깅(GUI 로그 창 포함)을 설정합니다.
        # 여기서의 기본 콘솔 로깅은 GUI가 완전히 시작되기 전이나 시작 실패 시 main_ebtg.py 자체의 메시지를 위함입니다.
        
        root_tk_window = tk.Tk()
        # EbtgGui 클래스는 EbtgAppService를 초기화하고 로깅을 설정합니다.
        _app_gui = EbtgGui(root_tk_window) # 생성된 인스턴스를 변수에 저장 (필요시 사용)
        root_tk_window.mainloop()
        logging.info("GUI 애플리케이션이 종료되었습니다.")

    except ImportError as e:
        logging.error(f"GUI를 시작하는 데 필요한 모듈을 임포트할 수 없습니다: {e}")
        logging.error("다음 사항을 확인하세요:")
        logging.error("  1. tkinter가 설치되어 있습니다 (Python 표준 라이브러리).")
        logging.error("  2. 'ebtg' 패키지 및 'ebtg.gui.ebtg_gui' 모듈이 프로젝트 내 올바른 위치에 있습니다.")
        logging.error("     (프로젝트 루트에 'ebtg' 폴더, 그 안에 'gui' 폴더 및 'ebtg_gui.py' 파일)")
        logging.error("  3. 스크립트를 프로젝트의 루트 디렉토리에서 실행하고 있습니다 (예: python main_ebtg.py --gui).")
        # 로깅이 완전히 설정되지 않았을 수 있으므로 stderr에도 출력
        print(f"ImportError: {e}. GUI를 실행할 수 없습니다. 상세 내용은 로그를 확인하세요.", file=sys.stderr)
    except Exception as e:
        logging.exception("GUI 실행 중 예기치 않은 오류 발생:") # .exception은 스택 트레이스를 포함
        print(f"Unexpected Error: {e}. GUI 실행 중 오류가 발생했습니다. 상세 내용은 로그를 확인하세요.", file=sys.stderr)


def run_cli_application(cli_args):
    """EBTG 애플리케이션을 (플레이스홀더) CLI 모드로 실행합니다."""
    logging.info("CLI 모드로 EBTG 애플리케이션을 시작합니다...")
    logging.info(f"사용된 설정 파일: {cli_args.config}")
    # if cli_args.verbose: # 상세 로깅 옵션 예시
    #     logging.getLogger().setLevel(logging.DEBUG)
    #     logging.debug("상세 로깅이 활성화되었습니다.")

    logging.info("EBTG CLI 초기화 중...")
    try:
        ebtg_instance = EBTG_Placeholder_CLI(config_path=cli_args.config)
        logging.info("CLI 초기화 완료.")
    except Exception as e:
        logging.exception("EBTG CLI 초기화 중 오류 발생:")
        return # 초기화 실패 시 종료

    logging.info("EBTG CLI 메인 로직 실행 중...")
    try:
        result = ebtg_instance.run()
        logging.info(f"EBTG CLI 실행 결과: {result}")
    except Exception as e:
        logging.exception("EBTG CLI 실행 중 오류 발생:")
        # 오류 처리 로직 (예: 추가 로그 남기기, 사용자에게 알림 등)

    logging.info("EBTG CLI 애플리케이션 실행이 완료되었습니다.")


def main():
    """
    EBTG 애플리케이션의 주 실행 함수.
    명령줄 인자를 통해 GUI 또는 CLI 모드로 실행할 수 있습니다.
    """
    # 메인 스크립트 자체를 위한 기본 콘솔 로깅 설정.
    # GUI 또는 CLI 특정 부분에서 이를 추가로 조정할 수 있습니다.
    logging.basicConfig(level=logging.INFO, 
                        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout)])

    parser = argparse.ArgumentParser(
        description="EBTG 애플리케이션 실행기.\nEPUB 번역을 위한 GUI 모드와 플레이스홀더 CLI 모드를 지원합니다.",
        formatter_class=argparse.RawTextHelpFormatter # 도움말 텍스트 형식 개선
    )
    
    parser.add_argument(
        "--gui",
        action="store_true",
        help="애플리케이션을 그래픽 사용자 인터페이스(GUI) 모드로 실행합니다.\n이 옵션을 사용하면 EPUB 번역기 GUI가 시작됩니다."
    )
    
    # CLI 모드 관련 인자 그룹
    cli_group = parser.add_argument_group('CLI 모드 옵션 (기본값으로 실행 시 사용)')
    cli_group.add_argument(
        "--config",
        help="CLI 모드에서 사용할 설정 파일 경로입니다. (기본값: config.ini)",
        default="config.ini",
        metavar="FILEPATH"
    )
    # 예시: CLI 상세 로깅 옵션 (필요시 확장)
    # cli_group.add_argument(
    #     "-v", "--verbose",
    #     action="store_true",
    #     help="CLI 모드에서 상세 로깅을 활성화합니다."
    # )

    args = parser.parse_args()

    if args.gui:
        run_gui_application()
    else:
        # --gui 플래그가 지정되지 않으면 CLI 모드로 기본 실행
        logging.info("명시적인 모드 선택이 없어 CLI 모드로 실행합니다. GUI를 사용하려면 --gui 플래그를 추가하세요.")
        run_cli_application(args)

# 5. 스크립트 직접 실행 시 main() 함수 호출
if __name__ == "__main__":
    # 이 조건문은 이 스크립트가 다른 곳에서 모듈로 임포트될 때는 main() 함수가 자동으로 실행되지 않도록 합니다.
    # 오직 'python main_ebtg.py'와 같이 직접 실행될 때만 main() 함수가 호출됩니다.
    main()
