# Real-Life BMO with Raspberry Pi

Inspired by a creative TikTok showcasing a real-life BMO, this project was my journey into bringing Adventure Time's BMO into the tangible world. When a friend gifted me a Raspberry Pi and a 3D printer, the idea of recreating BMO became irresistible. What started as an inspiration transformed into a month-long passion project, involving meticulous 3D printing, hardware interfacing, and software development.

## 🎨 Features:

### **3D Printed Model**
- Leveraging custom-tweaked design files, BMO was brought to life with nearly a week of dedicated 3D printing.

### **Hardware Interfacing**
- Buttons connected directly to the Raspberry Pi's GPIO pins enable users to engage with BMO seamlessly.

### **Voice Command Detection**
- A dynamic Python script constantly listens for voice commands, triggering responses or actions based on its internal intelligent phrase matching system.

### **Advanced Text-to-Speech (TTS)**
- Incorporated [Eleven Labs](https://elevenlabs.io/speech-synthesis)' AI for the initial TTS conversion.
- The output undergoes further refinement through a custom-trained BMO voice model, thanks to [mangio-RVC](https://github.com/Mangio621/Mangio-RVC-Fork).

## 🌟 Future Plans:
- **Virtual Assistant Capabilities**: BMO's skill set is set to grow! Aiming to incorporate Chat GPT for internet search capabilities to rival virtual assistants like Siri or Alexa.
- **Gaming Fun**: Plans to bring in Retro Pi are underway, enabling BMO to emulate classic games for hours of nostalgic entertainment.

## 🙏 Acknowledgements:
- Immense gratitude to the original TikTok creator for sparking the idea and providing the foundational design.
- Shoutout to [Eleven Labs](https://elevenlabs.io/speech-synthesis) and [mangio-RVC](https://github.com/Mangio621/Mangio-RVC-Fork) for their exceptional tools that added layers of authenticity to the project.

## 🤝 Contributing:
Though a personal passion project, I'm open to suggestions and contributions! If you have ideas or spot any bugs:
- Fork the repository and submit a pull request.
- Alternatively, feel free to open an issue. Let's make BMO better, together!

## 🛠️ Setup Notes (Raspberry Pi)

### Dependencies
- Python packages: install via `pip install -r requirements.txt` to pull in `kivy`, `speechrecognition`, `pvporcupine`, `pvrecorder`, `fuzzywuzzy`, and supporting audio drivers.
- System audio: ensure ALSA utilities are present (`sudo apt-get install alsa-utils portaudio19-dev`).

### Facial animation / visemes
- PNG or JPG face frames in `faces/` drive lip-sync and idle expressions. Files are ordered alphabetically, so keep leading numbers to control intensity levels from idle to the largest mouth shape.
- Idle faces can be `.jpg` or `.png` in the same folder; they are chosen randomly when BMO is not speaking.
- The playback loop samples audio energy (WAV files) in 80ms windows to determine which PNG to display. Other formats still animate using a synthesized timing curve, so keep a few distinct mouth PNGs for clearer motion.
- To add a new viseme: drop the PNG into `faces/`, restart the app, and confirm it appears in the sorted order. Pair your PNG names with expected intensity (low numbers = closed mouth, high numbers = open mouth) for smooth interpolation.
- Current faces are named after the expressions/mouth shapes they represent (e.g., `00-neutral-smile.jpg`, `06-wide-rectangle-shout.jpg`, `11-frown-deep.jpg`, `20-wide-grin.jpg`) so it is clear which frames to reuse or replace when tuning visemes.

### Fish Audio text-to-speech configuration
BMO now uses the Fish Audio API for synthesizing dialogue. Configure the API key and optional settings via environment variables before launching the app (add them to your shell profile or service unit so they persist on boot):

```bash
export FISH_AUDIO_API_KEY="<your-api-key>"
export FISH_AUDIO_BASE_URL="https://api.fish.audio/v1"  # optional override for self-hosted gateways
export FISH_AUDIO_MODEL="gpt_sovits"                     # optional model name
export FISH_AUDIO_SPEAKER_ID="bmo"                       # optional speaker or voice preset
```

If the API call fails, BMO will play an error voice clip and retry the request automatically before giving up.

### Picovoice wake word configuration
1. Create a [Picovoice Console](https://console.picovoice.ai/) account and generate an **AccessKey**.
2. Download a Porcupine keyword model (`.ppn`) tuned for your wake phrase (or use the built-in `bumblebee` keyword).
3. Provide credentials and models to the app via environment variables:
   ```bash
   export PICOVOICE_ACCESS_KEY="<your-access-key>"
   export PICOVOICE_KEYWORD_PATH="/path/to/keyword.ppn"  # omit to use the bundled "bumblebee" model
   export PICOVOICE_DEVICE_INDEX=0  # optional: ALSA input index for your microphone
   ```

### Raspberry Pi audio tips
- Confirm your microphone is recognized: `arecord -l` should list the capture card/device.
- Set the default input level with `alsamixer` and unmute the capture channel if needed.
- If you have multiple inputs, adjust the `PICOVOICE_DEVICE_INDEX` (matching the `arecord -l` listing) so wake-word detection listens to the correct device.
- Keep the mic close to BMO and reduce background noise for best wake-word detection accuracy.
