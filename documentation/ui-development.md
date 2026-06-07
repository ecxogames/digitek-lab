# UI Development: Navigation

The ESD Suite Framework uses a standard Webview for its frontend, meaning you can use standard web technologies (HTML, CSS, JavaScript) to build your pages.

## 1. Navigation Between Pages

Navigate using relative paths, evaluated from the currently loaded HTML file.

**HTML Links:**
```html
<a href="settings.html">Go to Settings</a>
```

**JavaScript:**
```javascript
window.location.href = "settings.html";
```

## 2. Web Components

For custom tags with encapsulated styles, use native browser Web Components:

```html
<script>
    class MyWidget extends HTMLElement {
        connectedCallback() {
            this.innerHTML = `<div>I am a custom widget!</div>`;
        }
    }
    customElements.define('my-widget', MyWidget);
</script>
<my-widget></my-widget>
```

## 3. Best Practices

* **Keep assets relative:** Use `./` or `../` for images, CSS, and JS so they resolve properly anywhere.
