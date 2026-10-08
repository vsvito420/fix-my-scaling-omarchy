# Fix my Scaling

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="72" height="72" role="img" aria-label="Icon Fix my Scaling">
  <defs><linearGradient id="fmsbg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1793d1"/><stop offset=".55" stop-color="#2bb3a0"/><stop offset="1" stop-color="#8ccf3c"/></linearGradient></defs>
  <rect width="128" height="128" rx="28" fill="url(#fmsbg)"/>
  <g fill="none" stroke="#fff" stroke-width="6" stroke-linejoin="round"><rect x="18" y="24" width="34" height="62" rx="5"/><rect x="58" y="40" width="54" height="34" rx="5"/></g>
  <g stroke-width="4" stroke-linecap="round"><line x1="22" y1="40" x2="48" y2="40" stroke="#ffd84a"/><line x1="22" y1="74" x2="48" y2="74" stroke="#ffd84a"/></g>
  <g fill="#fff"><rect x="60" y="99" width="8" height="8" rx="2"/><rect x="28" y="99" width="8" height="8" rx="2"/></g>
</svg>

Ein kleines Tool für Omarchy / Hyprland: Zwei Monitore unterschiedlicher Größe, Auflösung oder Drehung
so einstellen, dass die Maus an der Kante nicht mehr springt und Fenster auf beiden gleich groß wirken.
Statt `position` und `scale` in der `monitors.lua` zu raten, zieht man zwei Linien – fertig in zwei Minuten.

![Fix my Scaling auf einem hochkant gedrehten Monitor neben einem 1440p-Monitor](https://raw.githubusercontent.com/vsvito420/fix-my-scaling-omarchy/main/screenshots/setup-de.png)

## Was es macht

- **Wo ist oben?** – beim Start zeigt jeder Monitor an allen vier Kanten „OBEN ist hier“
  - man tippt die Kante, die in echt oben ist, der Monitor dreht sich passend
  - erst danach geht die Ausrichtung los, mit der richtigen Lage
- **Grüne Marker** – ein Monitor zeigt die obere und untere Ecke der gemeinsamen Kante
- **Gelbe Linien** – auf dem anderen zieht man sie, bis sie *physisch* auf gleicher Höhe sind
  - Maus, Finger oder Pfeiltasten (<kbd>↑</kbd>/<kbd>↓</kbd> 1 px, mit <kbd>Shift</kbd> 10 px)
- **Ergebnis** – Höhenversatz und passende Skalierung, damit beide die gleiche echte Pixeldichte haben
  - schlägt Skalierungs-Paare vor, die Hyprland sauber annimmt (z. B. `1.6 / 1.333 ±0.4 %`)
- **Live testen** – ohne zu speichern, Maus über die Kante schieben
- **Speichern** – schreibt die `monitors.lua`, lädt neu und prüft auf Überlappungen
- **Extras**
  - links/rechts wählbar, vertauschte Monitore mit einem Klick korrigiert
  - gedrehte Monitore: Drehung wird abgefragt und mitgespeichert, Modus bleibt erhalten
  - Touch-Test: jeder Tipp wird ein roter Punkt
  - Deutsch / Englisch nach Systemsprache

![Bedienfeld auf dem Hauptmonitor](https://raw.githubusercontent.com/vsvito420/fix-my-scaling-omarchy/main/screenshots/main-de.png)

## Installieren

```bash
git clone https://github.com/vsvito420/fix-my-scaling-omarchy.git
cd fix-my-scaling-omarchy
./install.sh
```

Danach **Monitor-Ausrichtung** im App-Starter (<kbd>Super</kbd> + <kbd>Space</kbd>) oder `fix-my-scaling` im Terminal.
Entfernen mit `./uninstall.sh` – die `monitors.lua` und ihre Backups bleiben.

## So funktioniert's

- **Code:** [`fix-my-scaling.py`](https://github.com/vsvito420/fix-my-scaling-omarchy/blob/main/fix-my-scaling.py) – nur Python-Standardbibliothek
- **Oberfläche:** ein kleiner Webserver (nur `127.0.0.1`, Zufallstoken pro Start) öffnet pro Monitor ein Chromium-App-Fenster im Vollbild
- **Rechnung:** Abstand der gelben Linien = echte Höhe des anderen Monitors in Pixeln dieses Monitors
  - daraus die Skalierung, gerundet auf Werte, die Hyprland sauber annimmt (ganze logische Pixel, 1/120-Schritte)
  - dann vertikal zwischen den Linien zentriert
- **Anwenden:** live per `hyprctl eval`, in sicherer Reihenfolge, damit nichts überlappt
- **Speichern:** ändert nur die `hl.monitor(...)`-Zeilen der beiden Monitore, vorher Backup `monitors.lua.bak.<zeit>`
  - schreibt exakte Brüche (`4/3` statt `1.33333`)
- **Voraussetzungen:** Hyprland mit Lua-Config, Python 3, ein Chromium-Browser (bei Omarchy dabei)

<div class="callout warning" markdown="1">
**Nicht mit dem Skalierungs-Regler im Omarchy-Tray mischen.** Der setzt die Skalierung für den fokussierten Monitor
mit `position = "auto"` – beim nächsten Neuladen springt es zurück und die Monitore können verrutschen.
</div>

<div class="callout tip" markdown="1">
Gedrehter Touchscreen, Tipps landen daneben? Touch an den Monitor binden und dieselbe Drehung setzen:
`hl.device({ name = "<touch-geraet>", output = "DP-1", transform = 1 })` – den Namen zeigt `hyprctl devices` unter *Touch*.
</div>

## Siehe auch

- [[Omarchy]]
- [[Sonnenkurve für die Bar]], [[Energieprofil-Tacho für die Bar]]
