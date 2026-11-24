<script setup>
import Container from '@/mini/components/Container.vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
</script>

<template>
  <Container>
    <Boxes spaceBot>
      <Box :size="100">
        <h1>Not found</h1>
        <p>There’s nothing at this address.</p>
        <RouterLink :to="{ name: 'dashboard' }" class="btn">Dashboard</RouterLink>
      </Box>
    </Boxes>
  </Container>
</template>
