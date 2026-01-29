# OneKeyVE
OneKeyWallerPaper

终于可以一键制作手机竖屏的动态壁纸啦  
适配比例1080/2400 1080/2376  
帧率看源  
需要补帧自行想办法  


# FFmpeg (BtbN 版) 下載與選型指南

針對 **OneKeyVE** 項目，建議從 [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds/releases/tag/latest) 下載。

### 1. 命名關鍵字拆解
文件名通常很長，例如：`ffmpeg-master-latest-win64-gpl.zip`，其含義如下：

| 關鍵字 | 說明 | 建議 |
| :--- | :--- | :--- |
| **win64** | Windows 64位元系統 | **必選** (除非你在 Linux 跑) |
| **gpl** | 包含所有主流編碼器 (x264, x265 等) | **推薦** (功能最全，無版權限制問題) |
| **lgpl** | 較寬鬆協議，但不含 x264/x265 | **不要選** (會導致無法合成 MP4) |
| **shared** | 運行依賴大量 DLL 動態庫 | **不推薦** (文件太碎，不方便攜帶) |
| **(無 shared)** | 靜態編譯版，所有功能集成在一個 exe | **強烈推薦** (單文件，最乾淨) |
| **master** | 最新開發分支，包含最新濾鏡 | **推薦** (功能最新) |

---

### 2. 推薦下載版本
為了配合 `OneKeyVE` 腳本，請直接搜索下載：
👉 **`ffmpeg-master-latest-win64-gpl.zip`**

---

### 3. 如何配置到項目中
1. 下載後解壓縮。
2. 進入 `bin` 文件夾，找到以下兩個核心文件：
   - `ffmpeg.exe` (負責視頻合成渲染)
   - `ffprobe.exe` (負責讀取視頻寬高、幀數)
3. 將這兩個 `.exe` 文件直接複製到 `OneKeyVE` 程序的根目錄（即與你的 `main.py` 或生成的 `.exe` 放在一起）。



---

### 4. 常見問題 (FAQ)
* **Q: 為什麼不用 lgpl 版本？**
  * A: 因為我們的腳本使用了 `libx264` (CPU) 和 `h264_nvenc` (GPU)，這些高效能編碼器只存在於 **GPL** 版本中。
* **Q: 下載後的 ffplay.exe 有什麼用？**
  * A: 它是一個簡易播放器，對於本项目沒有用處，可以放心刪除以節省空間。