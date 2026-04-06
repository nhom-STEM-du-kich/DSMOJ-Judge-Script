import subprocess
import os
import requests
import time
import multiprocessing
import json
import shutil

# --- CẤU HÌNH ---
API_GET_TASK = 'http://localhost:8000/api/get-task'
API_UPDATE_RESULT = 'http://localhost:8000/api/update-result'
API = 'http://localhost:8000/api/'
NUM_WORKERS = 4 
JUDGE_API_KEY = '2211ac5a-2f6d-4d8c-b80b-fae4482d6dc8'
HEADERS = {
    'X-DSMOJ-Auth': JUDGE_API_KEY,
    'Content-Type': 'application/json'
}
SUPPORTED_LANGUAGES = "C++ (GCC), ASM (NASM)"
MACHINE_LANGUAGES = ["cpp", "nasm"]
def build_test_log(count, status, input_str, expected, actual, exec_time, test_view, sub_id=None):
    """Xây dựng log HTML chuyên nghiệp"""
    color = "green" if status == "AC" else "#ff4d4d"
    sub_label = f"<span style='color:#888;'>[Subtask {sub_id}]</span> " if sub_id else ""
    log = f"<div style='border-bottom: 1px solid #444; padding: 10px; margin-bottom: 5px; background: #1e1e1e; color: #ddd;'>"
    log += (f"<b style='font-size: 1.1em;'>{sub_label}Test {count}: <span style='color:{color}'>{status}</span> "
            f"<span style='color: #888; font-weight: normal; font-size: 0.9em; margin-left: 10px;'>({exec_time}ms)</span></b>")
    if test_view:
        log += (f"<div style='margin-top: 8px; margin-left: 15px; font-family: \"JetBrains Mono\", monospace; "
                f"background: #000; padding: 10px; border-radius: 4px; border: 1px solid #333; font-size: 0.9em;'>"
                f"<p style='margin: 3px 0;'><b>Input:</b> <span style='color: #00e5ff;'>{input_str}</span></p>"
                f"<p style='margin: 3px 0;'><b>Expected:</b> <span style='color: #7cfc00;'>{expected.strip()}</span></p>"
                f"<p style='margin: 3px 0;'><b>Your Output:</b> <span style='color: {color};'>{actual.strip() if actual else 'None'}</span></p></div>")
    log += "</div>"
    return log

def run_judging(cmd, input_str, time_limit, expected_output, work_dir):
    """Sandbox bwrap cô lập hoàn toàn"""
    abs_work_dir = os.path.abspath(work_dir)
    bwrap_cmd = [
        'bwrap', '--ro-bind', '/usr', '/usr', '--ro-bind', '/lib', '/lib',
        '--ro-bind', '/lib64', '/lib64', '--ro-bind', '/bin', '/bin',
        '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
        '--bind', abs_work_dir, abs_work_dir, '--unshare-all',
        '--new-session', '--die-with-parent', '--chdir', abs_work_dir, '--'
    ] + cmd

    start_time = time.perf_counter()
    try:
        proc = subprocess.Popen(bwrap_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = proc.communicate(input=input_str, timeout=time_limit)
        exec_time = int((time.perf_counter() - start_time) * 1000)
        
        if proc.returncode != 0: return (stderr or "Runtime Error", 'RE', exec_time)
        status = 'AC' if stdout.strip() == expected_output.strip() else 'WA'
        return (stdout, status, exec_time)
    except subprocess.TimeoutExpired:
        if proc: proc.kill()
        return (None, 'TLE', int(time_limit * 1000))
    except Exception as e:
        return (str(e), 'ERROR', 0)

def worker_main(worker_id):
    work_dir = f'worker_dir_{worker_id}'
    os.makedirs(work_dir, exist_ok=True)
    print(f"[Worker {worker_id}] Pháo đài đã sẵn sàng!")

    while True:
        try:
            resp = requests.get(API_GET_TASK, timeout=5, headers=HEADERS)
            if resp.status_code != 200 or resp.json().get('status') == 'empty':
                time.sleep(1); continue
            
            task = resp.json()
            sub_id, user_code = task['id'], task['code']
            time_limit, lang = float(task['time_limit']), task['lang']
            test_view = task.get('test_view', False)
            
            # Parse testcases an toàn
            try:
                tc_data = json.loads(task['testcases']) if isinstance(task['testcases'], str) else task['testcases']
                subtasks = tc_data.get('subtasks', [])
            except:
                print(f"[Worker {worker_id}] Lỗi định dạng JSON bài #{sub_id}"); continue

            print(f"[Worker {worker_id}] Chấm bài #{sub_id} ({lang})")
            overall_status, html_logs, total_score, cmd = "AC", "", 0, []
            created_files = [] # Danh sách dọn dẹp

            # --- ENGINE BIÊN DỊCH ---
            try:
                if lang == "py":
                    f_name = f'sol_{sub_id}.py'
                    with open(os.path.join(work_dir, f_name), 'w') as f: f.write(user_code)
                    cmd, created_files = ['python3', f_name], [f_name]
                elif lang == "cpp":
                    f_cpp, f_out = f'sol_{sub_id}.cpp', f'sol_{sub_id}.out'
                    with open(os.path.join(work_dir, f_cpp), 'w') as f: f.write(user_code)
                    cp = subprocess.run(['g++', '-O2', os.path.join(work_dir, f_cpp), '-o', os.path.join(work_dir, f_out)], stderr=subprocess.PIPE, text=True)
                    created_files = [f_cpp, f_out]
                    if cp.returncode != 0: overall_status, html_logs = "CE", f"<pre style='color:orange;'>{cp.stderr}</pre>"
                    else: cmd = [f'./{f_out}']
                elif lang == "asm":
                    f_asm, f_obj, f_out = f'sol_{sub_id}.asm', f'sol_{sub_id}.o', f'sol_{sub_id}.out'
                    with open(os.path.join(work_dir, f_asm), 'w') as f: f.write(user_code)
                    created_files = [f_asm, f_obj, f_out]
                    as_p = subprocess.run(['nasm', '-f', 'elf64', os.path.join(work_dir, f_asm), '-o', os.path.join(work_dir, f_obj)], stderr=subprocess.PIPE, text=True)
                    if as_p.returncode != 0: overall_status, html_logs = "CE", f"<pre style='color:orange;'>NASM:\n{as_p.stderr}</pre>"
                    else:
                        ld_p = subprocess.run(['ld', os.path.join(work_dir, f_obj), '-o', os.path.join(work_dir, f_out)], stderr=subprocess.PIPE, text=True)
                        if ld_p.returncode != 0: overall_status, html_logs = "CE", f"<pre style='color:orange;'>Linker:\n{ld_p.stderr}</pre>"
                        else: cmd = [f'./{f_out}']

                # --- LOGIC CHẤM ĐIỂM OI ---
                if overall_status != "CE":
                    global_test_count, already_failed = 0, False
                    for sub in subtasks:
                        sub_ok, sub_log = True, ""
                        for tc in sub.get('testcases', []):
                            global_test_count += 1
                            actual, status, exec_time = run_judging(cmd, tc['input'], time_limit, tc['output'], work_dir)
                            sub_log += build_test_log(global_test_count, status, tc['input'], tc['output'], actual, exec_time, test_view, sub_id=sub.get('id'))
                            if status != "AC":
                                sub_ok = False
                                if not already_failed: overall_status, already_failed = status, True
                                if sub.get('method') == 'all_or_nothing': break
                        if sub_ok: total_score += sub.get('score', 0)
                        html_logs += sub_log

            finally:
                # --- TÍNH NĂNG TỰ ĐỘNG DỌN DẸP ---
                for f in created_files:
                    try: os.remove(os.path.join(work_dir, f))
                    except: pass
                print(f"[Worker {worker_id}] Đã dọn dẹp file bài #{sub_id}")

            requests.post(f"{API_UPDATE_RESULT}/{sub_id}/", json={"status": overall_status, "log": html_logs, "score": total_score},headers=HEADERS)
            print(f"[Worker {worker_id}] Xong #{sub_id} -> {overall_status} ({total_score} pts)")
        except Exception as e:
            print(f"Lỗi hệ thống: {e}"); time.sleep(2)
        except ConnectionError as e:
            print("connection error")

if __name__ == "__main__":
    requests.post(f"{API}ruok/", json={"status": "ON", "supported_languages": f"{SUPPORTED_LANGUAGES}", "languages_matrix": f"{MACHINE_LANGUAGES}"},headers=HEADERS)
    processes = [multiprocessing.Process(target=worker_main, args=(i,)) for i in range(NUM_WORKERS)]
    for p in processes: p.start()
    try:
        for p in processes: p.join()
    except KeyboardInterrupt:
        requests.post(f"{API}ruok/", json={"status": "OF", "supported_languages": f"{SUPPORTED_LANGUAGES}"},headers=HEADERS)
        for p in processes: p.terminate()
