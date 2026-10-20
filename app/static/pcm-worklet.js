/**
 * 麦克风采集处理器。
 *
 * 只做一件事：把每 128 帧的 Float32 数据复制一份丢给主线程。
 * 重采样、转 16-bit、分帧都在主线程做——worklet 里跑太重的循环会掉帧。
 */
class PCMCapture extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel && channel.length) {
      // slice 复制一份：底层 buffer 会被复用，不复制拿到的就是脏数据
      this.port.postMessage(channel.slice(0));
    }
    return true;
  }
}

registerProcessor("pcm-capture", PCMCapture);
