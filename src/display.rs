pub struct Display {
    pub width: usize,
    pub height: usize,
    buffer: Vec<bool>,
}

impl Display {
    pub fn new(width: usize, height: usize) -> Self {
        Display {
            width,
            height,
            buffer: vec![false; width * height],
        }
    }

    pub fn clear(&mut self) {
        for pixel in self.buffer.iter_mut() {
            *pixel = false;
        }
    }

    pub fn set_pixel(&mut self, x: usize, y: usize, on: bool) {
        // TODO: forward pixel state change to hardware via SPI/I2C
        if x < self.width && y < self.height {
            self.buffer[y * self.width + x] = on;
        }
    }

    pub fn get_pixel(&self, x: usize, y: usize) -> bool {
        if x < self.width && y < self.height {
            self.buffer[y * self.width + x]
        } else {
            false
        }
    }

    // TODO: flush the pixel buffer to the LCD hardware over the bus
    pub fn render(&self) {
        for row in 0..self.height {
            let line: String = (0..self.width)
                .map(|col| if self.buffer[row * self.width + col] { '#' } else { '.' })
                .collect();
            println!("{}", line);
        }
    }

    // TODO: implement character glyph lookup and blit each glyph into the buffer
    pub fn draw_text(&mut self, _text: &str, _x: usize, _y: usize) {
        todo!("draw_text: glyph rendering not yet implemented")
    }
}
