class VoiceCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.samples = new Float32Array(4096);
    this.offset = 0;
    this.total = 0;
    this.finished = false;
    this.port.onmessage = event => {
      if (event.data === "stop") this.finish();
    };
  }
  flush() {
    if (!this.offset) return;
    const buffer = this.samples.slice(0, this.offset).buffer;
    this.port.postMessage({ type: "samples", buffer }, [buffer]);
    this.offset = 0;
  }
  finish() {
    if (this.finished) return;
    this.finished = true;
    this.flush();
    this.port.postMessage({ type: "done" });
  }
  process(inputs) {
    if (this.finished) return false;
    const channels = inputs[0];
    if (!channels?.length) return true;
    for (let index = 0; index < channels[0].length; index++) {
      let sample = 0;
      for (const channel of channels) sample += channel[index] / channels.length;
      this.samples[this.offset++] = sample;
      this.total++;
      if (this.offset === this.samples.length) this.flush();
      if (this.total >= sampleRate * 60) {
        this.finish();
        return false;
      }
    }
    return true;
  }
}
registerProcessor("tenali-voice-capture", VoiceCapture);
