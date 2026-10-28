"""Operaciones comunes para interactuar con la aplicación."""

from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class BasePage:
    def __init__(self, driver, timeout=45):
        self.driver = driver
        self.wait = WebDriverWait(driver, timeout)

    def visible(self, locator):
        return self.wait.until(EC.visibility_of_element_located(locator))

    def click(self, locator):
        element = self.wait.until(EC.element_to_be_clickable(locator))
        self.driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', behavior: 'instant'})",
            element,
        )
        element.click()

    def fill(self, locator, value):
        element = self.visible(locator)
        element.clear()
        element.send_keys(value)

    def hidden(self, locator):
        return self.wait.until(EC.invisibility_of_element_located(locator))
