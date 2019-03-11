# -*- coding: utf-8 -*-
#!/usr/bin/env python3

"""
Adapted from : https://colab.research.google.com/notebooks/magenta/gansynth/gansynth_demo.ipynb
"""

from magenta import music
from magenta.models.nsynth.utils import load_audio
from magenta.models.gansynth.lib import flags as lib_flags, generate_util as gu, model as lib_model, util
from librosa import cqt, midi_to_hz

import os, sys
import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf

from config import *
from utils import get_extension, without_extension

def usage():
    print("Usage: python3 gansynth.py <path_to_model> <path_to_output_dir> <path_to_midi_file:optional>")

if len(sys.argv) < 3:
    usage()
    raise SystemExit

## Variables ##

ckpt_dir, output_dir = sys.argv[1], sys.argv[2]

batch_size = 16
sample_rate = SAMPLE_RATE

# Make an output directory if it doesn't exist
output_dir = util.expand_path(output_dir)
if not tf.gfile.Exists(output_dir):
    tf.gfile.MakeDirs(output_dir)

# Load the model
tf.reset_default_graph()
flags = lib_flags.Flags({'batch_size_schedule': [batch_size]})
model = lib_model.Model.load_from_path(ckpt_dir, flags)

# Helper functions
def load_midi(midi_path, min_pitch=36, max_pitch=84):
    """Load midi as a notesequence."""
    midi_path = util.expand_path(midi_path)
    ns = music.midi_file_to_sequence_proto(midi_path)
    pitches = np.array([n.pitch for n in ns.notes])
    velocities = np.array([n.velocity for n in ns.notes])
    start_times = np.array([n.start_time for n in ns.notes])
    end_times = np.array([n.end_time for n in ns.notes])
    valid = np.logical_and(pitches >= min_pitch, pitches <= max_pitch)
    notes = {'pitches': pitches[valid],
             'velocities': velocities[valid],
             'start_times': start_times[valid],
             'end_times': end_times[valid]}
    return ns, notes

def get_envelope(t_note_length, t_attack=0.010, t_release=0.3, sr=16000):
    """Create an attack sustain release amplitude envelope."""
    t_note_length = min(t_note_length, 3.0)
    i_attack = int(sr * t_attack)
    i_sustain = int(sr * t_note_length)
    i_release = int(sr * t_release)
    i_tot = i_sustain + i_release  # attack envelope doesn't add to sound length
    envelope = np.ones(i_tot)
    # Linear attack
    envelope[:i_attack] = np.linspace(0.0, 1.0, i_attack)
    # Linear release
    envelope[i_sustain:i_tot] = np.linspace(1.0, 0.0, i_release)
    return envelope

def combine_notes(audio_notes, start_times, end_times, velocities, sr=16000):
    """Combine audio from multiple notes into a single audio clip.

    Args:
    audio_notes: Array of audio [n_notes, audio_samples].
    start_times: Array of note starts in seconds [n_notes].
    end_times: Array of note ends in seconds [n_notes].
    sr: Integer, sample rate.

    Returns:
    audio_clip: Array of combined audio clip [audio_samples]
    """
    n_notes = len(audio_notes)
    clip_length = end_times.max() + 3.0
    audio_clip = np.zeros(int(clip_length) * sr)

    for t_start, t_end, vel, i in zip(start_times, end_times, velocities, range(n_notes)):
        # Generate an amplitude envelope
        t_note_length = t_end - t_start
        envelope = get_envelope(t_note_length)
        length = len(envelope)
        audio_note = audio_notes[i, :length] * envelope
        # Normalize
        audio_note /= audio_note.max()
        audio_note *= (vel / 127.0)
        # Add to clip buffer
        clip_start = int(t_start * sr)
        clip_end = clip_start + length
        audio_clip[clip_start:clip_end] += audio_note
        
    # Normalize
    audio_clip /= audio_clip.max()
    audio_clip /= 2.0
    return audio_clip

# Plotting tools
def specplot(audio_clip):
    p_min = np.min(36)
    p_max = np.max(84)
    f_min = midi_to_hz(p_min)
    f_max = 2 * midi_to_hz(p_max)
    octaves = int(np.ceil(np.log2(f_max) - np.log2(f_min)))
    bins_per_octave = 36
    n_bins = int(bins_per_octave * octaves)
    C = cqt(audio_clip, sr=SR, hop_length=2048, fmin=f_min, n_bins=n_bins, bins_per_octave=bins_per_octave)
    power = 10 * np.log10(np.abs(C)**2 + 1e-6)
    plt.matshow(power[::-1, 2:-2], aspect='auto', cmap=plt.cm.magma)
    plt.yticks([])
    plt.xticks([])

"""## 2(a): Random Interpolation

These cells take the MIDI for a full song and interpolate between several random latent vectors (equally spaced in time) over the whole song. The result sounds like instruments that slowly and smoothly morph between each other.
"""

midi_path = DEFAULT_MIDI
if len(argv) >  3:
  midi_path = sys.argv[3]

ns, notes = load_midi(midi_path)

if PLOT:
    print('Loaded {}'.format(midi_path))
    music.plot_sequence(ns)

seconds_per_instrument = 5

# Distribute latent vectors linearly in time
z_instruments, t_instruments = gu.get_random_instruments(model, notes['end_times'][-1], secs_per_instrument=seconds_per_instrument)

# Get latent vectors for each note
z_notes = gu.get_z_notes(notes['start_times'], z_instruments, t_instruments)

if DEBUG:
    print('Generating {} samples...'.format(len(z_notes)))

# Generate audio for each note
audio_notes = model.generate_samples_from_z(z_notes, notes['pitches'])

# Make a single audio clip
audio_clip = combine_notes(audio_notes, notes['start_times'], notes['end_times'], notes['velocities'])

if PLOT:
    print('CQT Spectrogram:')
    specplot(audio_clip)

# Write the file
fname = os.path.join(output_dir, 'generated_clip.wav')
gu.save_wav(audio_clip, fname)

# Load Default, but slow it down 30%
ns, notes_2 = load_midi(midi_path)
notes_2['start_times'] *= 1.3
notes_2['end_times'] *= 1.3

if PLOT:
    print('Loaded {}'.format(midi_path))
    music.plot_sequence(ns)

number_of_random_instruments = 10
pitch_preview = 60
n_preview = number_of_random_instruments

pitches_preview = [pitch_preview] * n_preview
z_preview = model.generate_z(n_preview)

audio_notes = model.generate_samples_from_z(z_preview, pitches_preview)

if DEBUG:
    for i, audio_note in enumerate(audio_notes):
        print("Instrument: {}".format(i))

instruments = [0, 2, 4, 0]

times = [0, 0.3, 0.6, 1.0]

# Force endpoints
times[0] = -0.001
times[-1] = 1.0

z_instruments = [z_preview[i] for i in instruments]
t_instruments = [notes_2['end_times'][-1] * t for t in times]

# Get latent vectors for each note
z_notes = gu.get_z_notes(notes_2['start_times'], z_instruments, t_instruments)

if DEBUG:
    print('Generating {} samples...'.format(len(z_notes)))
    
# Generate audio for each note
audio_notes = model.generate_samples_from_z(z_notes, notes_2['pitches'])

# Make a single audio clip
audio_clip = combine_notes(audio_notes, notes_2['start_times'], notes_2['end_times'], notes_2['velocities'])

if PLOT:
    print('CQT Spectrogram:')
    specplot(audio_clip)

# Write the file
fname = os.path.join(output_dir, 'generated_clip_2.wav')
gu.save_wav(audio_clip, fname)
