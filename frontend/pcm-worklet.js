// AudioWorklet: forwards mono Float32 microphone samples to the page in ~4096-sample batches.
// Resampling and WAV encoding happen on the page (wav.js) so this file has no imports.
class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buf = new Float32Array(4096);
    this.n = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (input && input.length > 0) {
      const channels = input.length;
      const frames = input[0].length;
      for (let i = 0; i < frames; i++) {
        let s = 0;
        for (let c = 0; c < channels; c++) s += input[c][i];
        this.buf[this.n++] = s / channels;
        if (this.n === this.buf.length) {
          this.port.postMessage(this.buf, [this.buf.buffer]);
          this.buf = new Float32Array(4096);
          this.n = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor('pcm-capture', PcmCapture);
