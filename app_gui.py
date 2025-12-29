import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import numpy as np
import datetime
import os
import sys
import csv
import time
from matplotlib import pyplot
import japanize_matplotlib

# ---------------------------------------------------------
# 【Windows用修正】 DLLパス設定
# ---------------------------------------------------------
if os.name == 'nt':
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    if hasattr(os, 'add_dll_directory'):
        try: os.add_dll_directory(base_path)
        except: pass
    os.environ['PATH'] = base_path + ';' + os.environ['PATH']

try:
    from rtlsdr import RtlSdr as RealRtlSdr
    HAS_HARDWARE_LIB = True
except ImportError:
    HAS_HARDWARE_LIB = False
    RealRtlSdr = None

# ---------------------------------------------------------
#  シミュレーション用 ダミークラス
# ---------------------------------------------------------
class MockRtlSdr:
    has_load_data = False
    def __init__(self):
        self.sample_rate = 2.048e6
        self.center_freq = 1420.4e6
        self.gain = 0
        self.driver_gain = 30.0
    def read_samples(self, count):
        count = int(count)
        noise = (np.random.randn(count) + 1j * np.random.randn(count)) * 0.1
        if MockRtlSdr.has_load_data:
            t = np.arange(count) / self.sample_rate
            f_sig = 0.05e6 
            signal = 0.008 * np.exp(1j * 2 * np.pi * f_sig * t)
            time.sleep(0.05) 
            return noise + signal
        else:
            time.sleep(0.05)
            return noise
    def close(self): pass
    def get_gain(self): return self.driver_gain
    def set_gain(self, g): self.driver_gain = g

# =========================================================
#  メインアプリケーション
# =========================================================
class Application(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.master.title('SDR 21cm Line Observer (Silent)')
        self.master.geometry("1100x900")

        os.makedirs("data", exist_ok=True)

        self.freq = [1420.4 -2.048/2 + 0.004 + 0.008*i for i in range(256)]
        self.pws_load = None 
        self.active_gain = 0
        self.var_sim_mode = tk.BooleanVar(value=True)
        self.processing_window = None

        self.notebook = ttk.Notebook(self.master)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.tab_obs = tk.Frame(self.notebook)
        self.notebook.add(self.tab_obs, text=" 観測 (Observation) ")
        self.setup_observation_tab()

        self.tab_ana = tk.Frame(self.notebook)
        self.notebook.add(self.tab_ana, text=" 解析 (Analysis) ")
        self.setup_analysis_tab()

    # =====================================================
    #  Tab 1: 観測機能 (Observation)
    # =====================================================
    def setup_observation_tab(self):
        input_frame = tk.Frame(self.tab_obs, pady=10)
        input_frame.pack(side=tk.TOP, fill=tk.X)
        fonts = ("MS Gothic", 12)

        tk.Label(input_frame, text="No:", font=fonts).pack(side=tk.LEFT, padx=5)
        self.entry_no = tk.Entry(input_frame, width=8, font=fonts)
        self.entry_no.insert(0, "001")
        self.entry_no.pack(side=tk.LEFT, padx=5)

        tk.Label(input_frame, text="Source:", font=fonts).pack(side=tk.LEFT, padx=5)
        self.entry_src = tk.Entry(input_frame, width=12, font=fonts)
        self.entry_src.insert(0, "MilkyWay")
        self.entry_src.pack(side=tk.LEFT, padx=5)

        tk.Label(input_frame, text="Duration(s):", font=fonts).pack(side=tk.LEFT, padx=5)
        self.entry_dur = tk.Entry(input_frame, width=6, font=fonts)
        self.entry_dur.insert(0, "30")
        self.entry_dur.pack(side=tk.LEFT, padx=5)

        chk_sim = tk.Checkbutton(input_frame, text="Simulation Mode", variable=self.var_sim_mode, font=("MS Gothic", 12, "bold"), fg="blue")
        chk_sim.pack(side=tk.RIGHT, padx=20)

        btn_frame = tk.Frame(self.tab_obs, pady=5)
        btn_frame.pack(side=tk.TOP, fill=tk.X)
        btn_font = ("MS Gothic", 11)
        
        self.btn_prep = tk.Button(btn_frame, text="準備 (Load計測)", command=self.prep, font=btn_font, bg="#d4edda", width=20, height=2)
        self.btn_prep.pack(side=tk.LEFT, padx=10)

        self.btn_sky = tk.Button(btn_frame, text="観測開始 (Sky計測)", command=self.sky_obs, font=btn_font, bg="#cce5ff", width=20, height=2)
        self.btn_sky.pack(side=tk.LEFT, padx=10)

        self.btn_clear = tk.Button(btn_frame, text="クリア", command=self.fig_clear_obs, font=btn_font, width=10, height=2)
        self.btn_clear.pack(side=tk.LEFT, padx=10)
        
        btn_quit = tk.Button(btn_frame, text="終了", command=self.master.destroy, font=btn_font, bg="#f8d7da", width=10, height=2)
        btn_quit.pack(side=tk.RIGHT, padx=10)

        graph_frame = tk.Frame(self.tab_obs)
        graph_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.fig_obs = Figure(figsize=(10.0, 6.0))
        self.ax_obs = self.fig_obs.add_subplot(1, 1, 1)
        self.canvas_obs = FigureCanvasTkAgg(self.fig_obs, graph_frame)
        self.toolbar_obs = NavigationToolbar2Tk(self.canvas_obs, graph_frame)
        self.canvas_obs.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.ax_obs.text(0.5, 0.5, "1. 観測情報を入力\n2. 準備 → 観測\n(観測番号は自動で進みます)", 
                     ha='center', va='center', fontname="MS Gothic", fontsize=24)
        self.ax_obs.axis('off')

    # =====================================================
    #  Tab 2: 解析機能 (Analysis)
    # =====================================================
    def setup_analysis_tab(self):
        self.path_on = tk.StringVar()
        self.path_off = tk.StringVar()

        file_frame = tk.LabelFrame(self.tab_ana, text="ファイル選択 (CSV)", pady=10, padx=10)
        file_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)
        
        f1_frame = tk.Frame(file_frame)
        f1_frame.pack(fill=tk.X, pady=2)
        tk.Label(f1_frame, text="ON (Raw) File:", width=15, anchor="e").pack(side=tk.LEFT)
        tk.Entry(f1_frame, textvariable=self.path_on, width=60).pack(side=tk.LEFT, padx=5)
        tk.Button(f1_frame, text="参照...", command=lambda: self.select_file(self.path_on)).pack(side=tk.LEFT)

        f2_frame = tk.Frame(file_frame)
        f2_frame.pack(fill=tk.X, pady=2)
        tk.Label(f2_frame, text="OFF (Load) File:", width=15, anchor="e").pack(side=tk.LEFT)
        tk.Entry(f2_frame, textvariable=self.path_off, width=60).pack(side=tk.LEFT, padx=5)
        tk.Button(f2_frame, text="参照...", command=lambda: self.select_file(self.path_off)).pack(side=tk.LEFT)

        set_frame = tk.Frame(self.tab_ana, pady=5)
        set_frame.pack(side=tk.TOP, fill=tk.X, padx=10)
        fonts = ("MS Gothic", 12)

        tk.Label(set_frame, text="Scan No:", font=fonts).pack(side=tk.LEFT, padx=5)
        self.entry_ana_no = tk.Entry(set_frame, width=10, font=fonts)
        self.entry_ana_no.insert(0, "Calc01")
        self.entry_ana_no.pack(side=tk.LEFT, padx=5)

        tk.Label(set_frame, text="Source:", font=fonts).pack(side=tk.LEFT, padx=5)
        self.entry_ana_src = tk.Entry(set_frame, width=15, font=fonts)
        self.entry_ana_src.insert(0, "Analyzed")
        self.entry_ana_src.pack(side=tk.LEFT, padx=5)

        tk.Button(set_frame, text="計算実行 & グラフ表示", command=self.run_analysis, 
                  bg="#ffc107", font=("MS Gothic", 11, "bold"), height=2).pack(side=tk.RIGHT, padx=20)

        graph_frame_ana = tk.Frame(self.tab_ana)
        graph_frame_ana.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.fig_ana = Figure(figsize=(10.0, 6.0))
        self.ax_ana = self.fig_ana.add_subplot(1, 1, 1)
        self.canvas_ana = FigureCanvasTkAgg(self.fig_ana, graph_frame_ana)
        self.toolbar_ana = NavigationToolbar2Tk(self.canvas_ana, graph_frame_ana)
        self.canvas_ana.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        self.ax_ana.text(0.5, 0.5, "CSVファイルを選択して「計算実行」を押してください。\n\n計算式: Value = ON - OFF", 
                     ha='center', va='center', fontname="MS Gothic", fontsize=16, color="#555")
        self.ax_ana.axis('off')


    def select_file(self, var_store):
        initial_dir = os.path.join(os.getcwd(), "data")
        if not os.path.exists(initial_dir):
            initial_dir = os.getcwd()
            
        path = filedialog.askopenfilename(
            initialdir=initial_dir,
            title="CSVファイルを選択",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
        )
        if path:
            var_store.set(path)

    def run_analysis(self):
        file_on = self.path_on.get()
        file_off = self.path_off.get()

        if not file_on or not file_off:
            messagebox.showerror("エラー", "ONファイルとOFFファイルの両方を選択してください。")
            return

        try:
            def read_csv_data(filepath):
                times = []
                values = []
                with open(filepath, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    rows = list(reader)
                    start_idx = 0
                    try:
                        float(rows[0][0])
                    except ValueError:
                        start_idx = 1
                    
                    for row in rows[start_idx:]:
                        if len(row) >= 2:
                            try:
                                times.append(float(row[0]))
                                values.append(float(row[1]))
                            except: pass
                return np.array(times), np.array(values)

            t_on, v_on = read_csv_data(file_on)
            t_off, v_off = read_csv_data(file_off)

            if len(v_on) == 0 or len(v_off) == 0:
                raise ValueError("データが読み込めませんでした。")
            
            min_len = min(len(v_on), len(v_off))
            t_on = t_on[:min_len]
            v_on = v_on[:min_len]
            v_off = v_off[:min_len]

            # 単純な引き算
            spectrum_diff = v_on - v_off

            self.ax_ana.clear()
            self.ax_ana.axis('on')
            self.ax_ana.plot(t_on, spectrum_diff, label="Spectrum Diff")
            
            no_str = self.entry_ana_no.get()
            src_str = self.entry_ana_src.get()
            
            self.ax_ana.set_title(f"Analysis: {no_str} {src_str} (ON - OFF)", fontsize=14)
            self.ax_ana.set_xlabel("Frequency [MHz]")
            self.ax_ana.set_ylabel("Intensity Difference [Linear]")
            self.ax_ana.grid(True)
            self.canvas_ana.draw()

            now_str = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
            base_name = f"data/{no_str}_{src_str}_diff_{now_str}"
            
            out_data = np.vstack([t_on, spectrum_diff]).T
            np.savetxt(f"{base_name}.csv", out_data, delimiter=",", header="Freq_MHz,Intensity_Diff_Linear", comments='')
            
            self.fig_ana.savefig(f"{base_name}.png")

            messagebox.showinfo("完了", f"計算が完了しました。\n\n保存先:\n{base_name}.csv")

        except Exception as e:
            messagebox.showerror("計算エラー", f"処理中にエラーが発生しました:\n{e}")

    # =====================================================
    #  観測用関数 (Tab 1用)
    # =====================================================
    def increment_no(self):
        current_val = self.entry_no.get().strip()
        if current_val.isdigit():
            length = len(current_val)
            next_val = int(current_val) + 1
            new_str = f"{next_val:0{length}d}"
            self.entry_no.delete(0, tk.END)
            self.entry_no.insert(0, new_str)

    def set_busy_state(self, is_busy, message="処理中..."):
        if is_busy:
            self.btn_prep.config(state=tk.DISABLED)
            self.btn_sky.config(state=tk.DISABLED)
            self.btn_clear.config(state=tk.DISABLED)
            
            self.processing_window = tk.Toplevel(self.master)
            self.processing_window.title("Processing")
            self.processing_window.geometry("400x150")
            x = self.master.winfo_x() + (self.master.winfo_width() // 2) - 200
            y = self.master.winfo_y() + (self.master.winfo_height() // 2) - 75
            self.processing_window.geometry(f"+{x}+{y}")
            self.processing_window.transient(self.master)
            self.processing_window.grab_set()
            
            tk.Label(self.processing_window, text=message, font=("MS Gothic", 16), fg="blue", name="lbl").pack(expand=True)
            self.processing_window.update()
        else:
            self.btn_prep.config(state=tk.NORMAL)
            self.btn_sky.config(state=tk.NORMAL)
            self.btn_clear.config(state=tk.NORMAL)
            if self.processing_window:
                self.processing_window.destroy()
                self.processing_window = None

    def update_busy_message(self, text):
        if self.processing_window:
            try:
                self.processing_window.nametowidget("lbl").config(text=text)
                self.processing_window.update()
            except: pass

    def _get_sdr_instance(self):
        is_sim = self.var_sim_mode.get()
        if is_sim: return MockRtlSdr()
        else:
            if not HAS_HARDWARE_LIB: raise Exception("RTL-SDRライブラリなし")
            try: return RealRtlSdr()
            except Exception as e: raise Exception(f"SDR接続エラー:\n{e}")

    def fig_clear_obs(self):
        self.ax_obs.clear()
        self.canvas_obs.draw()

    def prep(self):
        self.fig_clear_obs()
        prep_duration = 5 
        try:
            self.set_busy_state(True, "SDR初期化中...")
            sdr = self._get_sdr_instance()
        except Exception as e:
            self.set_busy_state(False)
            messagebox.showerror("初期化エラー", str(e))
            return

        try:
            sdr.sample_rate = 2.048e6
            sdr.center_freq = 1420.4e6

            self.update_busy_message("最適ゲイン探索中...")
            Glist = [2,3,6,9,11,14,16,17,19,21,22,25,27,29,32,34,36,37,38,40,42,43,44,45,47,50]
            gain = Glist[0]
            is_sim = self.var_sim_mode.get()

            for k in range(len(Glist)):
                sdr.gain = Glist[k]
                dat = sdr.read_samples(2.048e6)
                r_hist, _ = np.histogram(dat.real, range=(-1, 1), bins=256)
                i_hist, _ = np.histogram(dat.imag, range=(-1, 1), bins=256)
                N0 = (r_hist/np.sum(r_hist)+i_hist/np.sum(i_hist))*256
                if is_sim and k > 3: gain = Glist[k]; break
                if np.max(N0) < 7:
                    gain = Glist[k]; break
                elif k == len(Glist)-1 and not is_sim:
                    raise Exception("入力レベル過小")

            sdr.gain = gain
            self.active_gain = gain

            pws_sum = np.zeros(256)
            for i in range(prep_duration):
                self.update_busy_message(f"Loadデータ取得中... {prep_duration - i}s")
                dat = sdr.read_samples(2.048e6)
                spec = np.fft.fftshift(np.fft.fft(dat))  
                pws_sum += np.sum((np.abs(spec/len(dat)*2)**2).reshape(256,-1),axis=1)

            sdr.close()
            self.pws_load = pws_sum / prep_duration
            if is_sim: MockRtlSdr.has_load_data = True

            self.ax_obs.text(0.1, 0.8, f"キャリブレーション完了 (Gain: {gain})", fontname="MS Gothic", fontsize=20)
            self.ax_obs.axis('off')
            self.canvas_obs.draw()
        except Exception as e:
            messagebox.showerror("準備エラー", str(e))
        finally:
            self.set_busy_state(False)

    def sky_obs(self):
        self.fig_clear_obs()
        if self.pws_load is None:
            messagebox.showerror("手順エラー", "準備(Load計測)を行ってください。")
            return
        
        no_str = self.entry_no.get().strip()
        src_str = self.entry_src.get().strip()
        dur_str = self.entry_dur.get().strip()
        is_sim = self.var_sim_mode.get()
        if not no_str or not src_str: return
        try: duration = int(dur_str)
        except: return

        try:
            self.set_busy_state(True, "観測中...")
            sdr = self._get_sdr_instance()
            sdr.sample_rate = 2.048e6
            sdr.center_freq = 1420.4e6
            sdr.gain = self.active_gain

            pws_sum = np.zeros(256)
            for i in range(duration):
                self.update_busy_message(f"積分中... {duration - i}s")
                dat = sdr.read_samples(2.048e6)
                spec = np.fft.fftshift(np.fft.fft(dat))  
                pws_sum += np.sum((np.abs(spec/len(dat)*2)**2).reshape(256,-1),axis=1)
            
            sdr.close()
            pws_sky = pws_sum / duration

            with np.errstate(divide='ignore', invalid='ignore'):
                spectrum_db = 10 * np.log10(pws_sky / self.pws_load)
            spectrum_db = np.nan_to_num(spectrum_db, nan=0.0)

            self.ax_obs.plot(self.freq, spectrum_db)
            self.ax_obs.set_xlabel('Frequency [MHz]')
            self.ax_obs.set_ylabel('Intensity [dB]')
            self.ax_obs.set_title(f"No.{no_str} {src_str}", fontsize=16)
            self.ax_obs.grid(True)
            self.canvas_obs.draw()

            base_name = f"data/{no_str}_{src_str}"
            dt = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
            np.savetxt(f"{base_name}_raw_{dt}.csv", np.vstack([self.freq, pws_sky]).T, delimiter=",", header="Freq,RawSky", comments='')
            np.savetxt(f"{base_name}_load_{dt}.csv", np.vstack([self.freq, self.pws_load]).T, delimiter=",", header="Freq,RawLoad", comments='')
            np.savetxt(f"{base_name}_spectrum_{dt}.csv", np.vstack([self.freq, spectrum_db]).T, delimiter=",", header="Freq,dB", comments='')
            
            self.increment_no()
            messagebox.showinfo("完了", "観測完了")

        except Exception as e:
            messagebox.showerror("観測エラー", str(e))
        finally:
            self.set_busy_state(False)

if __name__ == "__main__":
    root = tk.Tk()
    app = Application(master=root)
    app.mainloop()