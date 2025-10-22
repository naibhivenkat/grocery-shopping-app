package com.example.groceryshoppingapp.adapters

import android.util.Log
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.bumptech.glide.Glide
import com.example.groceryshoppingapp.R
import com.example.groceryshoppingapp.models.Item

class ShopkeeperItemAdapter(
    private val items: MutableList<Item>,
    private val onItemLongClick: (Item) -> Unit
) : RecyclerView.Adapter<ShopkeeperItemAdapter.ItemViewHolder>() {

    inner class ItemViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        val itemImage: ImageView = itemView.findViewById(R.id.itemImage)
        val itemName: TextView = itemView.findViewById(R.id.itemName)
        val itemPrice: TextView = itemView.findViewById(R.id.itemPrice)
        val itemStock: TextView = itemView.findViewById(R.id.tv_item_quantity)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ItemViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_list_row, parent, false)
        return ItemViewHolder(view)
    }

    override fun onBindViewHolder(holder: ItemViewHolder, position: Int) {
        val item = items[position]
        holder.itemName.text = item.name
        holder.itemPrice.text = "₹%.2f".format(item.price)
        holder.itemStock.text = "Stock: ${item.stockQuantity}"

        val imageUrl = item.imageUrl?.trim()

        if (!imageUrl.isNullOrEmpty()) {
            val imageToLoad = when {
                imageUrl.startsWith("http", true) ->
                    imageUrl  // full URL from backend
                imageUrl.startsWith("images/", true) ->
                    "file:///android_asset/$imageUrl"  // asset reference (e.g. images/fruits/apple.jpg)
                imageUrl.startsWith("/images/", true) ->
                    "file:///android_asset${imageUrl}" // handles accidental leading slash
                else -> null
            }

            if (imageToLoad != null) {
                Log.d("ShopkeeperItemAdapter", "✅ Loading image: $imageToLoad")
                Glide.with(holder.itemView.context)
                    .load(imageToLoad)
                    .placeholder(R.drawable.image_placeholder)
                    .error(R.drawable.image_placeholder)
                    .centerCrop()
                    .into(holder.itemImage)
            } else {
                Log.w("ShopkeeperItemAdapter", "⚠️ Unknown image path for item: ${item.name}")
                holder.itemImage.setImageResource(R.drawable.image_placeholder)
            }
        } else {
            Log.w("ShopkeeperItemAdapter", "⚠️ No image URL for item: ${item.name}")
            holder.itemImage.setImageResource(R.drawable.image_placeholder)
        }

        holder.itemView.setOnLongClickListener {
            onItemLongClick(item)
            true
        }
    }

    override fun getItemCount(): Int = items.size
}
