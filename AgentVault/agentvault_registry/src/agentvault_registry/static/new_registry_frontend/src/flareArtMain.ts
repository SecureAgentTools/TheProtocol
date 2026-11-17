// V0665 art: mounts the contributor track's review gallery on its own (flare-art.html, dev server only). The same view is the admin
// route #/admin/flare-art; this entry exists so the gallery can be opened and photographed without a sign-in on a dev build.
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import i18n from './i18n'
import './assets/styles/main.css'
import './assets/styles/neural-command.css'
import Gallery from './views/AdminFlareArtGallery.vue'

createApp(Gallery).use(createPinia()).use(i18n).mount('#app')
