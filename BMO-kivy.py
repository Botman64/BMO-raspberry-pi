import os
os.environ['KIVY_AUDIO'] = 'sdl2'
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.core.audio import SoundLoader
from kivy.uix.video import Video
from kivy.clock import Clock
import threading
import time
import speech_recognition as sr
from fuzzywuzzy import process
import random
import pvporcupine
from pvrecorder import PvRecorder

TALKING_VIDEO = './Videos/talking.mp4'


responses = {
    "hello": [
        {"audio": "./responses/hello-1.wav"},
        {"audio": "./responses/hello-2.wav"},
        {"audio": "./responses/hello-3.wav"}
    ],
    "how are you": [
        {"audio": "./responses/how-are-you-1.wav"},
        {"audio": "./responses/how-are-you-2.wav"},
        {"audio": "./responses/how-are-you-3.wav"}
    ],

    "sing me a song": [
        {"audio": "./songs/Fly me to the Moon.mp3", "picture": "./pictures/space-cowboy.jpg"},
        {"audio": "./songs/I Dont Want to Set the World on Fire.mp3", "picture": "./pictures/cowboy.PNG"},
        {"audio": "./songs/Rises the Moon.mp3", "picture": "./pictures/happy.PNG"},
        {"audio": "./songs/From The Start.mp3", "picture": "./pictures/song-face.PNG"}
    ],
    "tell me something funny":[
        {"audio": "./memes/SIX-CONSOLES.wav", "picture": "./pictures/song-face.PNG"},
    ],

    "what time is it": [
        {"video": "./Videos/Original-Intro.mp4"},
        {"video": "./Videos/Bad-Jubies-intro.mp4"},
        {"video": "./Videos/elements-intro.mp4"},
        {"video": "./Videos/Finale-intro.mp4"},
        {"video": "./Videos/Food-Chain-intro.mp4"},
        {"video": "./Videos/Islands-intro.mp4"},
        {"video": "./Videos/Pixel-intro.mp4"},
        {"video": "./Videos/Stakes-intro.mp4"}
    ],
    "tell me a story": [
        {"video": "./Videos/boat-story.mp4"},
        {"video": "./Videos/Robot-Cowboy.mp4"},
    ],
    "goodnight": [
        {"audio": "./responses/goodnight.wav"}
    ]
}

image_directory = "./faces"
images = [os.path.join(image_directory, f) for f in os.listdir(image_directory) if f.endswith('.jpg')]


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

    def build(self):
        self.layout = BoxLayout()
        self.image = Image(source=random.choice(images), allow_stretch=True)
        self.layout.add_widget(self.image)

        self.power_up()

        return self.layout

    def power_up(self):
        self.command_enabled = False
        self.stop_wake_word_listener()
        self.play_power_up_sequence()

    def power_down(self):
        self.command_enabled = False
        self.stop_wake_word_listener()
        self.play_power_down_sequence()

    def change_face(self, *args):
        self.image.source = random.choice(images)

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
            self.image = Image(source=random.choice(images), allow_stretch=True)
            self.layout.add_widget(self.image)

    def check_video_position(self, instance, value):
        """Stop the video if it exceeds the specified duration."""
        if value >= self.max_video_duration:
            instance.state = 'stop'
            self.layout.clear_widgets()
            self.image = Image(source=random.choice(images), allow_stretch=True)
            self.layout.add_widget(self.image)

    def talk_audio(self, audio_path, on_complete=None):
        """Play an audio and loop a 1-second video until the audio is finished."""
        self.is_playing = True
        self.on_audio_complete = on_complete
        sound = SoundLoader.load(audio_path)
        if sound:
            duration = sound.length
            self.play_video_for_duration(TALKING_VIDEO, duration)
            sound.play()
            sound.bind(on_stop=self.on_audio_end)

    def play_static_audio_with_image(self, audio_path, image_path):
        """Play an audio and display a specified image until the audio finishes."""
        self.is_playing = True
        self.show_image_while_song_plays(image_path)
        sound = SoundLoader.load(audio_path)
        if sound:
            sound.play()
            sound.bind(on_stop=self.on_audio_end)

    def show_image_while_song_plays(self, image_path):
        self.layout.clear_widgets()
        song_image = Image(source=image_path, allow_stretch=True)
        self.layout.add_widget(song_image)

    def on_audio_end(self, *args):
        self.is_playing = False
        self.end_song_display()
        callback = self.on_audio_complete
        self.on_audio_complete = None
        if callback:
            callback()
        elif self.command_enabled:
            self.awaiting_command = False

    def end_song_display(self, *args):
        self.layout.clear_widgets()
        self.image = Image(source=random.choice(images), allow_stretch=True)
        self.layout.add_widget(self.image)
        if self.command_enabled:
            self.awaiting_command = False
            self.start_wake_word_listener()

    def listen_for_command(self, *args):
        if self.is_playing or not self.command_enabled:  # If a video or audio is currently playing, don't listen for commands
            return

        self.awaiting_command = True
        r = sr.Recognizer()
        with sr.Microphone() as source:
            audio = r.listen(source)

        try:
            speech_text = r.recognize_google(audio)
            # if "hey BeeMo" not in speech_text.upper():  # Checks if wake word "BMO" is in the recognized text
            #     return

            closest_match, score = process.extractOne(speech_text, responses.keys())
            if score >= 80:
                self.process_command(closest_match)
        except sr.UnknownValueError:
            self.talk_audio("./responses/unknown-value-error.wav")  # Placeholder for error audio
        except sr.RequestError:
            self.talk_audio("./responses/fatal-error.wav")  # Placeholder for error audio
        finally:
            self.awaiting_command = False

    def process_command(self, command):
        self.is_playing = True
        if command == "goodnight":
            self.power_down()
            return
        
        response_options = responses[command]
        selected_response = random.choice(response_options)
        
        if selected_response.get("audio"):
            if selected_response.get("picture"):
                # Display the specified picture with the audio
                self.play_static_audio_with_image(selected_response["audio"], selected_response["picture"])
            else:
                # If there's no picture, use the talking video as default
                self.talk_audio(selected_response["audio"])
        
        # If there's a video (and it's not the TALKING_VIDEO), play it
        if selected_response.get("video") and selected_response.get("video") != TALKING_VIDEO:
            self.play_video(selected_response["video"])

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
