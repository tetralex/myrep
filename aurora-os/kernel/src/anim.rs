//! Animationen: Werte, die sich über die Zeit mit einer „Easing“-Kurve ändern.
//! Lineare Bewegung wirkt mechanisch – echte Dinge beschleunigen und bremsen.

pub fn ease_out_cubic(t: f32) -> f32 {
    let u = 1.0 - t;
    1.0 - u * u * u
}

pub fn ease_in_out_cubic(t: f32) -> f32 {
    if t < 0.5 {
        4.0 * t * t * t
    } else {
        let u = -2.0 * t + 2.0;
        1.0 - u * u * u / 2.0
    }
}

/// Ein Wert, der von `from` nach `to` wandert (Zeiten in Millisekunden)
#[derive(Clone, Copy)]
pub struct Tween {
    pub from: f32,
    pub to: f32,
    start: u64,
    duration: u64,
    ease: fn(f32) -> f32,
}

impl Tween {
    pub fn fixed(v: f32) -> Self {
        Tween { from: v, to: v, start: 0, duration: 1, ease: ease_out_cubic }
    }

    pub fn new(from: f32, to: f32, start: u64, duration: u64, ease: fn(f32) -> f32) -> Self {
        Tween { from, to, start, duration: duration.max(1), ease }
    }

    /// Vom aktuellen Wert aus zu einem neuen Ziel aufbrechen
    pub fn retarget(&mut self, to: f32, now: u64, duration: u64, ease: fn(f32) -> f32) {
        *self = Tween::new(self.value(now), to, now, duration, ease);
    }

    pub fn progress(&self, now: u64) -> f32 {
        if now <= self.start { 0.0 } else { ((now - self.start) as f32 / self.duration as f32).min(1.0) }
    }

    pub fn value(&self, now: u64) -> f32 {
        self.from + (self.to - self.from) * (self.ease)(self.progress(now))
    }

    pub fn running(&self, now: u64) -> bool {
        now < self.start + self.duration + 1
    }
}
