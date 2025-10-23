package com.example.groceryshoppingapp.adapters

import android.app.Activity
import android.app.AlertDialog
import android.text.InputType
import android.util.Log
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.recyclerview.widget.RecyclerView
import com.bumptech.glide.Glide
import com.example.groceryshoppingapp.R
import com.example.groceryshoppingapp.models.Item

class ItemAdapter(
    private var items: List<Item> = listOf(),
    private val onItemClick: (Item, String) -> Unit // pass item + quantity with unit
) : RecyclerView.Adapter<ItemAdapter.ItemViewHolder>() {

    fun updateItems(newItems: List<Item>) {
        items = newItems
        notifyDataSetChanged()
    }

    inner class ItemViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        val itemImage: ImageView = itemView.findViewById(R.id.itemImage)
        val itemName: TextView = itemView.findViewById(R.id.itemName)
        val itemPrice: TextView = itemView.findViewById(R.id.itemPrice)
        val addButton: Button = itemView.findViewById(R.id.addButton)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ItemViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_row, parent, false)
        return ItemViewHolder(view)
    }

    override fun onBindViewHolder(holder: ItemViewHolder, position: Int) {
        val item = items[position]

        // Name & price
        holder.itemName.text = item.name
        holder.itemPrice.text = "₹%.2f".format(item.price)

        // Load image (asset or URL)
        item.imageUrl?.trim()?.let { url ->
            val imageToLoad = when {
                url.startsWith("http", true) -> url
                url.startsWith("images/", true) -> "file:///android_asset/$url"
                url.startsWith("/images/", true) -> "file:///android_asset$url"
                else -> null
            }

            Glide.with(holder.itemView.context)
                .load(imageToLoad ?: R.drawable.image_placeholder)
                .placeholder(R.drawable.image_placeholder)
                .error(R.drawable.image_placeholder)
                .centerCrop()
                .into(holder.itemImage)
        } ?: holder.itemImage.setImageResource(R.drawable.image_placeholder)

        // Add button → show quantity & unit dialog
        holder.addButton.setOnClickListener {
            val ctx = holder.itemView.context
            if (ctx is Activity && !ctx.isFinishing) {
                showQuantityDialog(holder, item)
            }
        }
    }

    private fun showQuantityDialog(holder: ItemViewHolder, item: Item) {
        val context = holder.itemView.context

        val layout = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(50, 20, 50, 10)
        }

        val quantityInput = EditText(context).apply {
            hint = "Enter quantity"
            inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
        }

        val unitSpinner = Spinner(context).apply {
            adapter = ArrayAdapter(
                context,
                android.R.layout.simple_spinner_dropdown_item,
                listOf("KG", "Grams", "Pcs")
            )
        }

        layout.addView(quantityInput)
        layout.addView(unitSpinner)

        AlertDialog.Builder(context)
            .setTitle("Select quantity for ${item.name}")
            .setView(layout)
            .setPositiveButton("Add") { _, _ ->
                val qty = quantityInput.text.toString().trim()
                val unit = unitSpinner.selectedItem.toString()

                if (qty.isEmpty()) {
                    Toast.makeText(context, "Please enter quantity", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }

                val finalQty = "$qty $unit"
                Log.d("ItemAdapter", "Adding ${item.name} → $finalQty")
                onItemClick(item, finalQty)
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    override fun getItemCount(): Int = items.size
}
