package com.gazeqa.generated;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

@DisplayName("Adjacency-based story lifecycle checks")
class AdjacencyStoryLifecycleTest {
  private static final Path RUN_ROOT = Path.of(".").toAbsolutePath().normalize();
  private static final Path STORIES_JSON = RUN_ROOT.resolve("../../frd/stories_export.json").normalize();
  private static final Path CRAWL_JSON = RUN_ROOT.resolve("../../source/crawl/crawl_result.json").normalize();

  private List<Map<String, Object>> loadStories() throws IOException {
    ObjectMapper mapper = new ObjectMapper();
    Map<String, Object> payload = mapper.readValue(
        Files.newBufferedReader(STORIES_JSON), new TypeReference<>() {});
    Object features = payload.get("features");
    if (!(features instanceof List<?> list)) {
      throw new IllegalStateException("features list missing");
    }
    @SuppressWarnings("unchecked")
    List<Map<String, Object>> typed = (List<Map<String, Object>>) list;
    return typed;
  }

  private Map<String, Map<String, Object>> loadCrawl() throws IOException {
    ObjectMapper mapper = new ObjectMapper();
    Map<String, Object> payload = mapper.readValue(
        Files.newBufferedReader(CRAWL_JSON), new TypeReference<>() {});
    @SuppressWarnings("unchecked")
    Map<String, Map<String, Object>> pages = (Map<String, Map<String, Object>>) payload.get("pages");
    return pages;
  }

  @Test
  @DisplayName("All adjacency stories exported")
  void allAdjacencyStoriesExported() throws IOException {
    Set<String> storyIds = loadStories().stream()
        .map(item -> (String) item.get("story_id"))
        .collect(Collectors.toSet());
    assertTrue(storyIds.contains("STORY-FR-006-ABOUT"));
    assertTrue(storyIds.contains("STORY-FR-006-TEAM"));
    assertTrue(storyIds.contains("STORY-FR-006-ADMIN"));
  }

  @Test
  @DisplayName("Admin page depth captured")
  void adminPageDepthCaptured() throws IOException {
    Map<String, Map<String, Object>> pages = loadCrawl();
    Map<String, Object> admin = pages.get("https://example.test/admin");
    assertEquals(2, ((Number) admin.get("depth")).intValue());
  }
}
