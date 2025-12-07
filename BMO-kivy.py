import audioop
import math
import os
import wave

os.environ['KIVY_AUDIO'] = 'sdl2'
from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.core.audio import SoundLoader
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.uix.video import Video
import pvporcupine
import random
import speech_recognition as sr
import threading
import time
from pvrecorder import PvRecorder

from command_router import CommandRouter
from fish_audio import FishAudioClient

TALKING_VIDEO = './Videos/talking.mp4'


image_directory = "./faces"


def _load_images_with_extensions(*extensions):
    return sorted(
        os.path.join(image_directory, f)
        for f in os.listdir(image_directory)
        if f.lower().endswith(extensions)
    )


images = _load_images_with_extensions(".jpg", ".png")


class BMOApp(App):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.is_playing = False  # Flag to check if video or audio is currently playing
        self.max_video_duration = 0
        self.command_enabled = False
        self.awaiting_command = False
        self.porcupine = None
        self.wake_listener_thread = None
        self.stop_listening_event = threading.Event()
        self.on_audio_complete = None
        self.device_index = int(os.environ.get("PICOVOICE_DEVICE_INDEX", 0))
        self.command_router = CommandRouter()
        self.tts_client = FishAudioClient()
        self.idle_faces = images
        self.viseme_frames = self._load_viseme_frames()
        self.idle_face_source = random.choice(self.idle_faces) if self.idle_faces else None
        self._viseme_clock = None
        self._viseme_points = []
        self._smoothed_intensity = 0.0
        self._audio_start_time = None
        self._active_sound = None

    def build(self):
        self.layout = BoxLayout()
        self.image = Image(source=self.idle_face_source, allow_stretch=True)
        self.layout.add_widget(self.image)

        self.power_up()

        return self.layout

    def _load_viseme_frames(self):
        visemes = [path for path in images if path.lower().endswith(".png")]
        return visemes if visemes else images

    def _prepare_face_canvas(self):
        if self.image not in self.layout.children or len(self.layout.children) != 1:
            self.layout.clear_widgets()
            self.layout.add_widget(self.image)
        if not self.image.source and self.idle_faces:
            self.image.source = random.choice(self.idle_faces)

    def _set_face_image(self, face_path):
        if not face_path:
            return
        if not self.image:
            return
        if self.image.source == face_path and self.image.opacity >= 1:
            return

        def _swap_source(*_):
            self.image.source = face_path
            Animation(opacity=1.0, d=0.08).start(self.image)

        Animation(opacity=0.0, d=0.08).bind(on_complete=_swap_source).start(self.image)

    def _choose_idle_face(self):
        return random.choice(self.idle_faces) if self.idle_faces else None

    def _analyze_audio_envelope(self, audio_path, duration):
        try:
            with wave.open(audio_path, "rb") as wav_file:
                frame_rate = wav_file.getframerate()
                sample_width = wav_file.getsampwidth()
                window_size = int(frame_rate * 0.08)
                timestamps = []
                values = []
                current_frame = 0
                data = wav_file.readframes(window_size)
                while data:
                    rms = audioop.rms(data, sample_width)
                    timestamps.append(current_frame / frame_rate)
                    values.append(rms)
                    current_frame += window_size
                    data = wav_file.readframes(window_size)

                if not values:
                    return []

                peak = max(values) or 1
                normalized = [(timestamps[i], values[i] / peak) for i in range(len(values))]
                if duration and normalized[-1][0] < duration:
                    normalized.append((duration, 0.0))
                return normalized
        except (wave.Error, FileNotFoundError, EOFError):
            return []

    def _interpolated_envelope(self, elapsed):
        if not self._viseme_points:
            return 0.5 + 0.5 * math.sin(elapsed * 8)

        for idx, (timestamp, value) in enumerate(self._viseme_points):
            if elapsed <= timestamp:
                if idx == 0:
                    return value
                prev_t, prev_v = self._viseme_points[idx - 1]
                progress = (elapsed - prev_t) / max(timestamp - prev_t, 1e-6)
                return prev_v + (value - prev_v) * progress
        return self._viseme_points[-1][1]

    def _drive_visemes(self, duration):
        if not self.is_playing:
            return False

        elapsed = time.time() - self._audio_start_time
        if duration and elapsed > duration + 0.25:
            self.on_audio_end()
            return False

        target_intensity = self._interpolated_envelope(elapsed)
        self._smoothed_intensity += (target_intensity - self._smoothed_intensity) * 0.35
        frame_count = len(self.viseme_frames) or 1
        frame_index = min(int(round(self._smoothed_intensity * (frame_count - 1))), frame_count - 1)
        self._set_face_image(self.viseme_frames[frame_index])
        return True

    def _start_viseme_loop(self, duration):
        self._stop_viseme_loop()
        self._audio_start_time = time.time()

        def _tick(dt):
            if not self._drive_visemes(duration):
                return False

        self._viseme_clock = Clock.schedule_interval(_tick, 1 / 30.0)

    def _stop_viseme_loop(self):
        if self._viseme_clock:
            self._viseme_clock.cancel()
            self._viseme_clock = None
        self._viseme_points = []
        self._smoothed_intensity = 0.0
        self._audio_start_time = None

    def power_up(self):
        self.command_enabled = False
        self.stop_wake_word_listener()
        self.play_power_up_sequence()

    def power_down(self):
        self.command_enabled = False
        self.stop_wake_word_listener()
        self.play_power_down_sequence()

    def change_face(self, *args):
        self.image.source = self._choose_idle_face()

    def play_video_for_duration(self, video_path, duration):
        """Play a video and loop it for the specified duration."""
        self.layout.clear_widgets()
        self.video_duration = duration
        self.video_start_time = time.time()  # Store the starting time
        
        video = Video(source=video_path, allow_stretch=True)
        video.bind(eos=self.loop_video)
        self.layout.add_widget(video)
        video.state = 'play'
        
    def loop_video(self, instance, state):
        """Restart the video if it hasn't reached the specified duration."""
        elapsed_time = time.time() - self.video_start_time
        if elapsed_time < self.video_duration:
            instance.seek(0)
            instance.state = 'play'
        else:
            instance.state = 'stop'
            self.layout.clear_widgets()
            self.image = Image(source=self._choose_idle_face(), allow_stretch=True)
            self.layout.add_widget(self.image)

    def check_video_position(self, instance, value):
        """Stop the video if it exceeds the specified duration."""
        if value >= self.max_video_duration:
            instance.state = 'stop'
            self.layout.clear_widgets()
            self.image = Image(source=self._choose_idle_face(), allow_stretch=True)
            self.layout.add_widget(self.image)

    def talk_audio(self, audio_path, on_complete=None):
        """Play an audio clip and animate viseme PNGs in sync with the waveform."""
        self.is_playing = True
        self.on_audio_complete = on_complete
        self._prepare_face_canvas()
        self._active_sound = SoundLoader.load(audio_path)
        if self._active_sound:
            duration = self._active_sound.length or 0
            self._viseme_points = self._analyze_audio_envelope(audio_path, duration)
            self._start_viseme_loop(duration)
            self._active_sound.play()
            self._active_sound.bind(on_stop=self.on_audio_end)
        else:
            self.is_playing = False
            self._resume_command_handling()

    def play_static_audio_with_image(self, audio_path, image_path):
        """Play an audio and display a specified image until the audio finishes."""
        self.is_playing = True
        self.show_image_while_song_plays(image_path)
        self._active_sound = SoundLoader.load(audio_path)
        if self._active_sound:
            self._active_sound.play()
            self._active_sound.bind(on_stop=self.on_audio_end)

    def show_image_while_song_plays(self, image_path):
        self.layout.clear_widgets()
        song_image = Image(source=image_path, allow_stretch=True)
        self.layout.add_widget(song_image)

    def on_audio_end(self, *args):
        self._stop_viseme_loop()
        self._active_sound = None
        self.is_playing = False
        self.end_song_display()
        self._set_face_image(self._choose_idle_face())
        callback = self.on_audio_complete
        self.on_audio_complete = None
        if callback:
            callback()
        else:
            self._resume_command_handling()

    def end_song_display(self, *args):
        self.layout.clear_widgets()
        self.image = Image(source=self._choose_idle_face(), allow_stretch=True)
        self.layout.add_widget(self.image)

    def listen_for_command(self, *args):
        if self.is_playing or not self.command_enabled:  # If a video or audio is currently playing, don't listen for commands
            return

        self.awaiting_command = True
        r = sr.Recognizer()
        with sr.Microphone() as source:
            audio = r.listen(source)

        try:
            speech_text = r.recognize_google(audio)
            self.process_command(speech_text)
        except sr.UnknownValueError:
            self.talk_audio("./responses/unknown-value-error.wav")  # Placeholder for error audio
        except sr.RequestError:
            self.talk_audio("./responses/fatal-error.wav")  # Placeholder for error audio
        finally:
            self.awaiting_command = False

    def process_command(self, command):
        if self.is_playing:
            return

        self.is_playing = True
        try:
            routed_response = self.command_router.route_command(command)
            reply_text = routed_response.content
            if reply_text:
                print(f"BMO: {reply_text}")
                self._speak_response(reply_text)
            else:
                self._handle_tts_failure("Empty response from router.")
        except Exception as exc:  # pragma: no cover - runtime guard
            print(f"Error while processing command: {exc}")
            self._handle_tts_failure(str(exc))

    def _speak_response(self, reply_text: str):
        try:
            audio_path = self.tts_client.synthesize_to_path(reply_text)
        except Exception as exc:  # pragma: no cover - runtime guard
            print(f"Fish Audio request failed: {exc}")
            self._handle_tts_failure(str(exc))
            return

        self.talk_audio(audio_path, on_complete=self._cleanup_temp_audio(audio_path))

    def _cleanup_temp_audio(self, audio_path: str):
        def _cleanup():
            try:
                if audio_path and os.path.exists(audio_path):
                    os.remove(audio_path)
            finally:
                self._resume_command_handling()

        return _cleanup

    def _resume_command_handling(self):
        if self.command_enabled:
            self.awaiting_command = False
            self.start_wake_word_listener()

    def _handle_tts_failure(self, reason: str):
        print(f"TTS failure: {reason}")
        self.talk_audio("./responses/fatal-error.wav")

    def play_video(self, video_path):
        self.layout.clear_widgets()
        video = Video(source=video_path, allow_stretch=True)
        video.bind(eos=self.on_video_end)
        self.layout.add_widget(video)
        video.state = 'play'

    def on_video_end(self, *args):
        self.is_playing = False
        self.layout.clear_widgets()
        self.image = Image(source=random.choice(images), allow_stretch=True)
        self.layout.add_widget(self.image)
        if self.command_enabled:
            self.awaiting_command = False
            self.start_wake_word_listener()

    def play_power_up_sequence(self):
        initial_audio_path = "./responses/startup.mp3"
        self.talk_audio(initial_audio_path, on_complete=self.enable_command_handling)

    def play_power_down_sequence(self):
        shutdown_audio_path = "./responses/goodnight.wav"
        self.talk_audio(shutdown_audio_path, on_complete=self.stop)

    def enable_command_handling(self):
        self.command_enabled = True
        self.start_wake_word_listener()

    def initialize_wake_word(self):
        if self.porcupine:
            return
        access_key = os.environ.get("PICOVOICE_ACCESS_KEY")
        keyword_path = os.environ.get("PICOVOICE_KEYWORD_PATH")
        keywords = None if keyword_path else ["bumblebee"]
        self.porcupine = pvporcupine.create(
            access_key=access_key,
            keyword_paths=[keyword_path] if keyword_path else None,
            keywords=keywords,
        )

    def start_wake_word_listener(self):
        if not self.command_enabled or self.is_playing:
            return

        self.initialize_wake_word()
        if self.wake_listener_thread and self.wake_listener_thread.is_alive():
            return

        self.stop_listening_event.clear()
        self.wake_listener_thread = threading.Thread(target=self._wake_word_loop, daemon=True)
        self.wake_listener_thread.start()

    def stop_wake_word_listener(self):
        self.stop_listening_event.set()
        if self.wake_listener_thread and self.wake_listener_thread.is_alive():
            self.wake_listener_thread.join()
        self.wake_listener_thread = None

    def _wake_word_loop(self):
        recorder = PvRecorder(device_index=self.device_index, frame_length=self.porcupine.frame_length)
        recorder.start()
        try:
            while not self.stop_listening_event.is_set():
                pcm = recorder.read()
                if self.porcupine.process(pcm) >= 0 and not self.awaiting_command and not self.is_playing:
                    self.awaiting_command = True
                    Clock.schedule_once(self.listen_for_command, 0)
        finally:
            recorder.stop()
            recorder.delete()

    def on_stop(self):
        self.stop_wake_word_listener()


BMOApp().run()
