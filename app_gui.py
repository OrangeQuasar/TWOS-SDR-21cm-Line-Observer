import tkinter as tk
from tkinter import messagebox
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import numpy as np
import datetime
import os
import sys
import argparse
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
        try:
            os.add_dll_directory(base_path)
        except Exception:
            pass
    os.environ['PATH'] = base_path + ';' + os.environ['PATH']

# ライブラリのインポート（失敗しても止まらず、フラグだけ立てる）
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
    # クラス変数としてLoad状態を共有（インスタンスが変わっても状態を維持するため）
    has_load_data = False

    def __init__(self):
        self.sample_rate = 2.048e6
        self.center_freq = 1420.4e6
        self.gain = 0
        self.driver_gain = 30.0

    def read_samples(self, count):
        count = int(count)
        # ベースノイズ
        noise = (np.random.randn(count) + 1j * np.random.randn(count)) * 0.1
        
        # フラグを見て信号を出すか決める
        if MockRtlSdr.has_load_data:
            t = np.arange(count) / self.sample_rate
            f_sig = 0.05e6 
            signal = 0.008 * np.exp(1j * 2 * np.pi * f_sig * t)
            return noise + signal
        else:
            return noise

    def close(self): pass
    def get_gain(self): return self.driver_gain
    def set_gain(self, g): self.driver_gain = g


class Application(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.master.title('SDR 21cm Line Observer (GUI Switchable)')
        self.master.geometry("1100x850")

        # データ保存用フォルダ作成
        os.makedirs("data", exist_ok=True)

        # 内部変数
        self.freq = [1420.4 -2.048/2 + 0.004 + 0.008*i for i in range(256)]
        self.pws_load = None 
        self.active_gain = 0
        
        # シミュレーションモード管理用変数
        self.var_sim_mode = tk.BooleanVar(value=True) # デフォルトはON

        # --- UI構築 ---
        self.create_widgets()
        
        # 初期描画
        self.ax.text(0.5, 0.5, "1. 観測情報を入力\n2. モードを選択 (Simulation or Real)\n3. 準備 → 観測", 
                     ha='center', va='center', fontname="MS Gothic", fontsize=24)
        self.ax.axis('off')
        self.fig_canvas.draw()

    def create_widgets(self):
        # 1. 入力エリア (上部)
        input_frame = tk.Frame(self.master, pady=10)
        input_frame.pack(side=tk.TOP, fill=tk.X)

        fonts = ("MS Gothic", 12)

        # 観測番号
        tk.Label(input_frame, text="No:", font=fonts).pack(side=tk.LEFT, padx=5)
        self.entry_no = tk.Entry(input_frame, width=8, font=fonts)
        self.entry_no.insert(0, "001")
        self.entry_no.pack(side=tk.LEFT, padx=5)

        # 天体名
        tk.Label(input_frame, text="Source:", font=fonts).pack(side=tk.LEFT, padx=5)
        self.entry_src = tk.Entry(input_frame, width=12, font=fonts)
        self.entry_src.insert(0, "MilkyWay")
        self.entry_src.pack(side=tk.LEFT, padx=5)

        # 積分時間
        tk.Label(input_frame, text="Duration(s):", font=fonts).pack(side=tk.LEFT, padx=5)
        self.entry_dur = tk.Entry(input_frame, width=6, font=fonts)
        self.entry_dur.insert(0, "30")
        self.entry_dur.pack(side=tk.LEFT, padx=5)

        # ★ シミュレーション切替チェックボックス
        chk_sim = tk.Checkbutton(input_frame, text="Simulation Mode", variable=self.var_sim_mode, font=("MS Gothic", 12, "bold"), fg="blue")
        chk_sim.pack(side=tk.RIGHT, padx=20)

        # 2. ボタンエリア
        btn_frame = tk.Frame(self.master, pady=5)
        btn_frame.pack(side=tk.TOP, fill=tk.X)

        btn_font = ("MS Gothic", 11)
        
        b_prep = tk.Button(btn_frame, text="準備 (Load計測)", command = self.prep, font=btn_font, bg="#d4edda", width=20, height=2)
        b_prep.pack(side=tk.LEFT, padx=10)

        b_sky = tk.Button(btn_frame, text="観測開始 (Sky計測)", command = self.sky_obs, font=btn_font, bg="#cce5ff", width=20, height=2)
        b_sky.pack(side=tk.LEFT, padx=10)

        b_clear = tk.Button(btn_frame, text="クリア", command = self.fig_clear, font=btn_font, width=10, height=2)
        b_clear.pack(side=tk.LEFT, padx=10)
        
        b_quit = tk.Button(btn_frame, text="終了", command = self.master.destroy, font=btn_font, bg="#f8d7da", width=10, height=2)
        b_quit.pack(side=tk.RIGHT, padx=10)

        # 3. グラフエリア
        graph_frame = tk.Frame(self.master)
        graph_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        fig = Figure(figsize=(10.0, 7.5))
        self.ax = fig.add_subplot(1, 1, 1)
        self.fig_canvas = FigureCanvasTkAgg(fig, graph_frame)
        self.toolbar = NavigationToolbar2Tk(self.fig_canvas, graph_frame)
        self.fig_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)


    def _get_sdr_instance(self):
        """現在のモードに応じたSDRインスタンスを返す"""
        is_sim = self.var_sim_mode.get()
        
        if is_sim:
            return MockRtlSdr()
        else:
            # 本番モードだがライブラリがない場合
            if not HAS_HARDWARE_LIB:
                raise Exception("RTL-SDRライブラリ(rtlsdr.dll等)が見つかりません。\nシミュレーションモードを使用してください。")
            
            # 本番モードでデバイス接続を試みる
            try:
                return RealRtlSdr()
            except Exception as e:
                # 接続エラー（USB未接続やドライバ不良）
                raise Exception(f"SDRデバイス接続エラー:\n{str(e)}\n\nUSB接続やドライバ(Zadig)を確認してください。")


    def fig_clear(self):
        self.ax.clear()
        self.fig_canvas.draw()


    def prep(self):
        self.ax.clear()
        self.fig_canvas.draw()
        
        # 準備用積分時間（短縮可能だが安定のため5秒）
        prep_duration = 5 

        try:
            # ★ ここでモードに応じたSDRを取得
            sdr = self._get_sdr_instance()
        except Exception as e:
            self.show_error("初期化エラー", str(e))
            return

        sdr.sample_rate = 2.048e6
        sdr.center_freq = 1420.4e6

        # --- オートゲイン調整 ---
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
                gain = Glist[k]
                break
            elif k == len(Glist)-1:
                if not is_sim:
                    self.show_error("入力過多", "入力レベルが低すぎます。接続を確認してください。")
                    sdr.close()
                    return

        sdr.gain = gain
        self.active_gain = gain

        # --- Loadデータ取得 ---
        pws_sum = np.zeros(256)
        for i in range(prep_duration):
            dat = sdr.read_samples(2.048e6)
            nData = len(dat)
            spec = np.fft.fftshift(np.fft.fft(dat))  
            pwrN = np.abs(spec/nData*2)**2
            pws_sum += np.sum(pwrN.reshape(256,int(nData/256)),axis=1)

        sdr.close()
        
        self.pws_load = pws_sum / prep_duration

        # シミュレーション用フラグ操作
        if is_sim:
            MockRtlSdr.has_load_data = True

        self.ax.text(0.1, 0.8, f"キャリブレーション完了 (Gain: {gain})", fontname="MS Gothic", fontsize=20)
        self.ax.text(0.1, 0.6, "内部にLoadデータを保持しました。", fontname="MS Gothic", fontsize=16)
        self.ax.axis('off')
        self.fig_canvas.draw()


    def sky_obs(self):
        self.ax.clear()

        if self.pws_load is None:
            self.show_error("手順エラー", "準備(Load計測)が完了していません。")
            return

        no_str = self.entry_no.get().strip()
        src_str = self.entry_src.get().strip()
        dur_str = self.entry_dur.get().strip()
        is_sim = self.var_sim_mode.get()

        if not no_str or not src_str:
            self.show_error("入力エラー", "No と Source を入力してください。")
            return

        try:
            duration = int(dur_str)
            if duration < 1: raise ValueError
        except:
            self.show_error("入力エラー", "Duration(秒) は正の整数で入力してください。")
            return

        try:
            sdr = self._get_sdr_instance()
        except Exception as e:
            self.show_error("デバイスエラー", str(e))
            return

        sdr.sample_rate = 2.048e6
        sdr.center_freq = 1420.4e6
        sdr.gain = self.active_gain

        # --- Skyデータ取得 ---
        pws_sum = np.zeros(256)
        
        # 簡易ループ (長時間のフリーズ回避にはthreadが必要ですが簡易版として実装)
        for i in range(duration):
            dat = sdr.read_samples(2.048e6)
            nData = len(dat)
            spec = np.fft.fftshift(np.fft.fft(dat))  
            pwrN = np.abs(spec/nData*2)**2
            pws_sum += np.sum(pwrN.reshape(256,int(nData/256)),axis=1)
            # ループ中にGUI更新を入れるとフリーズしてるように見えない
            if i % 5 == 0:
                self.master.update()

        sdr.close()

        pws_sky = pws_sum / duration

        # --- dB計算 ---
        with np.errstate(divide='ignore', invalid='ignore'):
            ratio = pws_sky / self.pws_load
            spectrum_db = 10 * np.log10(ratio)
        
        spectrum_db = np.nan_to_num(spectrum_db, nan=0.0)

        # --- 描画 ---
        self.ax.plot(self.freq, spectrum_db)
        self.ax.set_xlabel('Frequency [MHz]')
        self.ax.set_ylabel('Relative Intensity [dB]')
        
        now = datetime.datetime.now()
        date_str = now.strftime("%Y%m%dT%H%M%S")
        title = f"No.{no_str} {src_str} ({date_str})"
        if is_sim: title += " [SIMULATED]"
        
        self.ax.set_title(title, fontsize = 16)
        self.ax.grid(True)
        self.fig_canvas.draw()

        # --- 保存 ---
        base_name = f"data/{no_str}_{src_str}"
        
        # 1. Raw Sky
        np.savetxt(f"{base_name}_raw_{date_str}.csv", np.vstack([self.freq, pws_sky]).T, 
                   delimiter=",", header=f"Freq,RawSky,Gain{self.active_gain}", comments='')
        # 2. Load
        np.savetxt(f"{base_name}_load_{date_str}.csv", np.vstack([self.freq, self.pws_load]).T, 
                   delimiter=",", header=f"Freq,RawLoad,Gain{self.active_gain}", comments='')
        # 3. Spectrum
        np.savetxt(f"{base_name}_spectrum_{date_str}.csv", np.vstack([self.freq, spectrum_db]).T, 
                   delimiter=",", header=f"Freq,dB,Gain{self.active_gain}", comments='')

        try:
            self.fig_canvas.print_png(f"{base_name}_plot_{date_str}.png")
        except: pass

        messagebox.showinfo("完了", f"観測完了\nNo: {no_str}, Source: {src_str}")


    def show_error(self, title, message):
        self.ax.clear()
        self.ax.text(0.5, 0.5, f"【{title}】\n{message}", 
                     ha='center', va='center', fontname="MS Gothic", fontsize=16, color="red")
        self.ax.axis('off')
        self.fig_canvas.draw()


parser = argparse.ArgumentParser(description='SDR Observation GUI')
args = parser.parse_args()

root = tk.Tk()
app = Application(master=root)
app.mainloop()