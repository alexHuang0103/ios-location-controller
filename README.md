# iPhone／iPad 模擬定位控制台

## Windows：第一次使用

1. 先安裝 Python 3.9 以上版本，開啟終端機（PowerShell 或命令提示字元），安裝 `pymobiledevice3`：

   ```powershell
   py -m pip install -U pymobiledevice3
   ```

2. 用 USB 連接 iPhone／iPad，解鎖裝置，並在裝置上點選「信任這部電腦」。
3. 在終端機輸入下列指令，讓裝置的「設定」顯示開發者模式選項：

   ```powershell
   py -m pymobiledevice3 amfi reveal-developer-mode
   ```

4. 到裝置的 **設定 → 隱私權與安全性 → 開發者模式**，開啟開發者模式。依畫面提示重新啟動，並在重啟後確認開啟。若選項原本就已出現且已開啟，可略過上一步的顯示指令。
5. 雙擊 [start.bat](start.bat)，瀏覽器會開啟 `http://127.0.0.1:8765`。第一次使用請先完成上面步驟，再啟動控制台。

## 使用網頁控制台

- **單點定位**：輸入經緯度，或直接點地圖選位置，再按「設定定位」。
- **移動路徑**：點「移動路徑」，依序在地圖上點起點、終點，再按「開始移動」。路線是直線，速度約 20 km/h，每 0.5 秒更新一次；單次最長 200 公里。「停止移動」會固定在當時的預估位置。
- **返回目前位置**：允許瀏覽器的位置權限後，地圖會顯示藍點；按地圖右上角按鈕可回到藍點。藍點是開啟控制台的瀏覽器取得的位置，可能只有約略位置，不能代表被模擬定位的裝置原本的真實 GPS。
- 使用後按「恢復真實定位」。頁面底部的「更多操作與說明」有「檢查 USB 裝置」和「關閉控制台」。
- 恢復真實定位時，控制台會重新連接開發者服務，可能需要一段時間。畫面若只出現 `RequestsDependencyWarning` 或「Trying again over a no-root userspace tunnel」，代表套件仍在嘗試連線，不代表已恢復成功；請等控制台顯示執行結果。

## 不用網頁，直接在終端機改位置

Mac 無法執行 `.bat`。若要在 Mac 使用，先安裝 Python 與 `pymobiledevice3`，再用 USB 連接、解鎖並信任 iPhone／iPad：

```sh
python3 -m pip install -U pymobiledevice3
python3 -m pymobiledevice3 amfi reveal-developer-mode
```

接著在裝置的 **設定 → 隱私權與安全性 → 開發者模式** 開啟開發者模式。已開啟時，不必重複執行顯示指令。

設定位置的範例（緯度 `25.0330`、經度 `121.5654`）：

**Windows**

```powershell
py -m pymobiledevice3 developer dvt simulate-location set -- 25.0330 121.5654
```

**macOS**

```sh
python3 -m pymobiledevice3 developer dvt simulate-location set -- 25.0330 121.5654
```

這個設定指令可能會持續執行，以維持定位連線。要結束時，在該終端機按 Enter；若要明確恢復真實定位，可另外執行：

**Windows**

```powershell
py -m pymobiledevice3 developer dvt simulate-location clear
```

**macOS**

```sh
python3 -m pymobiledevice3 developer dvt simulate-location clear
```

以上 DVT 指令適用於 iOS／iPadOS 17 以上；較舊版本的定位指令不同。

## 提醒

- 網頁控制台只在本機 `127.0.0.1` 運作；地圖底圖需要網路，但輸入座標與定位指令會送到本機服務。
- 控制台只允許啟動一份。若要載入更新後的程式，先在頁面按「關閉控制台」，再重新雙擊 `start.bat`。
- 若裝置無法連線，先確認 USB 線、解鎖與「信任這部電腦」，再用 `py -m pymobiledevice3 usbmux list`（Mac 用 `python3 -m ...`）檢查。
- DDI 是開發者服務用的映像檔。若終端機的定位指令已成功，不需要在介面手動掛載。

參考：[pymobiledevice3 安裝說明](https://github.com/doronz88/pymobiledevice3/blob/master/docs/installation.md)、[定位指令範例](https://github.com/doronz88/pymobiledevice3/blob/master/docs/guides/cli-recipes.md)、[Apple 開發者模式說明](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device)。
