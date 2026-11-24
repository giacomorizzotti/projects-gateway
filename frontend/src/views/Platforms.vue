<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Server } from '@iconoir/vue'
import Container from '@/mini/components/Container.vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
import Space from '@/mini/components/Space.vue'
import LoadingBox from '@/mini/components/LoadingBox.vue'
import Button from '@/mini/components/Button.vue'
import PlatformForm from '@/components/forms/PlatformForm.vue'
import { useCatalogStore } from '@/stores/catalog'
import CatalogCounts from '@/components/CatalogCounts.vue'
import { ipFamilies } from '@/utils/format'

const catalog = useCatalogStore()
const router = useRouter()
onMounted(() => catalog.load())

const creating = ref(false)
function onCreated(platform) {
  creating.value = false
  router.push({ name: 'platform', params: { slug: platform.slug } })
}
</script>

<template>
  <Container>
    <Boxes class="align-items-start">
      <Box :size="100">
        <h1 class="m-0">Platforms</h1>
        <p class="m-0 light-grey-text">Where every environment runs.</p>
        <CatalogCounts class="mt-05 mb-15"/>
        <Space/>
        <p class="m-0">
          <Button :disabled="!catalog.choices" @click="creating = true" size="S" class="platform-btn" hard>+ New platform</Button>
        </p>
      </Box>
    </Boxes>
    <Space height="2"/>
    <Boxes spaceBot class="mb-2 align-items-start">
      <Box :size="100" v-if="catalog.loading && !catalog.choices"><LoadingBox dark/></Box>
      <Box :size="100" v-else-if="catalog.error"><p class="danger-box">{{ catalog.error }}</p></Box>
      <Box :size="100" class="py-0">
        <Boxes gap="2">
          <Box v-for="pl in catalog.platforms" :key="pl.slug" :size="25" padding="0">
            <div class="project-card p-15 platform-border fb-bg" style="border-top: 3px solid;">
              <p class="S mb-05">
                <span class="dark-grey-box platform-text XS">{{ pl.kind_label }}</span>
              </p>
              <h4 class="m-0 platform-text">
                <Server width="0.9em" height="0.9em" aria-hidden="true" style="vertical-align: -0.1em" class="me-1 platform-text"/>
                <RouterLink :to="{ name: 'platform', params: { slug: pl.slug } }" class="platform-text underline">
                  {{ pl.name }}
                </RouterLink>
              </h4>
              <p class="S m-0 flex g-0 align-items-start">
                <span class="muted-text">{{ [pl.provider, pl.location].filter(Boolean).join('&nbsp;&nbsp;·&nbsp;&nbsp;') }}</span>
              </p>
              <Space/>
              <p class="S m-0 wrap-anywhere">
                <template v-if="pl.dynamic_dns"><span class="me-075">Dynamic IP</span><code class="my-025 me-05 black-bg platform-text">{{ pl.dynamic_dns }}</code></template>
                <template v-else>
                  <span v-for="f in ipFamilies(pl.public_ips)" :key="f.label" class="block">
                    <span class="XS white-text me-075">{{ f.label }}</span><code v-for="ip in f.ips" :key="ip" class="my-025 me-05 black-bg platform-text">{{ ip }}</code>
                  </span>
                </template>
              </p>
              <Space/>
              <p class="S m-0 grey-text">{{ pl.environment_count }} environment{{ pl.environment_count === 1 ? '' : 's' }}</p>
            </div>
          </Box>
        </Boxes>
      </Box>
    </Boxes>

    <PlatformForm :visible="creating" @close="creating = false" @saved="onCreated"/>
  </Container>
</template>
