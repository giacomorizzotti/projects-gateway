<script setup>
// Shown instead of the app when its sign-in settings can't be loaded (main.js): the gateway or
// its auth server isn't answering, or sign-in isn't set up (the server's log says which).
// Sheet + Main.black-bg as in App.vue: the page's text is white (main.scss).
import Sheet from '@/mini/components/Sheet.vue'
import Main from '@/mini/components/Main.vue'
import Container from '@/mini/components/Container.vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
import Space from '@/mini/components/Space.vue'

function retry() {
  window.location.reload()
}
</script>

<template>
  <Sheet>
    <Main class="black-bg">
      <Container>
        <Boxes spaceTopBot fh class="align-content-start">
          <Box :size="100">
            <Space height="2"/>
            <h1 class="m-0">Sign in</h1>
            <p>Sign-in isn’t available right now. Please try again in a moment.</p>
            <button class="btn" @click="retry">Try again</button>
          </Box>
        </Boxes>
      </Container>
    </Main>
  </Sheet>
</template>
