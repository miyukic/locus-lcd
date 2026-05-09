mod display;

use display::Display;

fn main() {
    let mut lcd = Display::new(16, 4);

    lcd.set_pixel(0, 0, true);
    lcd.set_pixel(7, 1, true);
    lcd.set_pixel(15, 3, true);

    lcd.render();
}
