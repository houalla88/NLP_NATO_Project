import wikipediaapi
import wikipedia

#print(wikipedia.search("NATO",results=100))
wikipedia.set_lang("ru")
print(wikipedia.page('Північноатланти́чний алья́нс').content)
